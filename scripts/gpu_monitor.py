#!/usr/bin/env python3
"""
GPU 负载监控 + 作业队列健康检查
每 10 分钟运行一次，检测：
1. GPU 3D 占用率是否持续低于 20%
2. 是否有作业卡住（transcribed=1 超过 30 分钟未完成）
3. 是否有作业积压（大量 transcribed=0 或 director_status=0 未处理）
4. GPU 队列是否出错

若 GPU 空闲且有积压，尝试修复：
- 重置卡住的作业
- 必要时重启 GPU 服务
"""
import sys
import os
import json
import time
import sqlite3
import subprocess
import urllib.request
from datetime import datetime

# Config
GPU_HOST = "10.190.0.203"
GPU_PORT = 8877
WATCHDOG_PORT = 8878
BACKEND_PORT = 8899
DB_PATH = "/Users/claw/work/douyin-recorder/douyin.db"
STATE_FILE = "/tmp/gpu_monitor_state.json"
LOW_GPU_THRESHOLD = 20  # 3D% below this is "idle"
LOW_GPU_CONSECUTIVE = 2  # need 2 consecutive checks (= 10 min) to trigger action

def http_get(url, timeout=10):
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}

def http_post(url, data=None, timeout=10):
    try:
        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(url, data=body, method="POST")
        if body:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return {"low_gpu_count": 0, "last_restart": 0}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def get_gpu_health():
    return http_get(f"http://{GPU_HOST}:{GPU_PORT}/health")

def get_watchdog_status():
    return http_get(f"http://{GPU_HOST}:{WATCHDOG_PORT}/status")

def restart_gpu_service():
    """通过 watchdog 重启 GPU 服务"""
    return http_post(f"http://{GPU_HOST}:{WATCHDOG_PORT}/restart/gpu")

def get_db_stats():
    """获取数据库中作业统计"""
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    stats = {}
    
    # 转录积压
    stats["transcribed_waiting"] = db.execute(
        "SELECT count(*) as c FROM recordings WHERE transcribed = 1"
    ).fetchone()["c"]
    
    stats["transcribed_ready"] = db.execute(
        "SELECT count(*) as c FROM recordings WHERE synced=0 AND transcribed=0 AND local_deleted=0 AND end_time IS NOT NULL AND end_time != start_time"
    ).fetchone()["c"]
    
    # 导演版积压（与 backfill 逻辑一致：需有有效的录制文件）
    stats["director_pending"] = db.execute(
        """SELECT count(*) as c FROM clip_groups
           WHERE classic_status = 2 AND director_status = 0
           AND EXISTS (
               SELECT 1 FROM recordings
               WHERE recordings.group_id = clip_groups.id
                 AND recordings.local_deleted = 0 AND recordings.clipped = 2
           )"""
    ).fetchone()["c"]
    
    stats["director_running"] = db.execute(
        "SELECT count(*) as c FROM clip_groups WHERE director_status = 1"
    ).fetchone()["c"]
    
    # creative 积压（与 backfill 逻辑一致：需有有效的录制文件）
    stats["creative_pending"] = db.execute(
        """SELECT count(*) as c FROM clip_groups
           WHERE classic_status = 2 AND director_status = 2 AND creative_status = 0
           AND EXISTS (
               SELECT 1 FROM recordings
               WHERE recordings.group_id = clip_groups.id
                 AND recordings.local_deleted = 0 AND recordings.clipped = 2
           )"""
    ).fetchone()["c"]
    
    stats["creative_running"] = db.execute(
        "SELECT count(*) as c FROM clip_groups WHERE creative_status = 1"
    ).fetchone()["c"]
    
    # 检查卡住的转录（transcribed=1 且录像较老）
    stats["stuck_transcriptions"] = db.execute("""
        SELECT count(*) as c FROM recordings 
        WHERE transcribed = 1 AND gpu_job_id IS NOT NULL
    """).fetchone()["c"]
    
    db.close()
    return stats

def fix_stuck_transcriptions():
    """修复卡住的转录作业：检查 GPU 上的状态，完成的拉回来
    
    注意：此函数只检查 transcribed=1（已提交 GPU）的记录。
    transcribed=0 的上传由后端 poll 循环自动处理，不需要干预。
    """
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT id, gpu_job_id, filename FROM recordings WHERE transcribed = 1 AND gpu_job_id IS NOT NULL"
    ).fetchall()
    
    fixed = 0
    reset = 0
    for r in rows:
        job_status = http_get(f"http://{GPU_HOST}:{GPU_PORT}/jobs/{r['gpu_job_id']}")
        if "error" in job_status:
            # GPU 上找不到 → 重置为 synced=0 让其重新上传
            db.execute(
                "UPDATE recordings SET synced=0, transcribed=0, gpu_job_id=NULL WHERE id=?",
                (r["id"],)
            )
            reset += 1
        elif job_status.get("status") == "done":
            # GPU 已完成但本地没拉回 → 标记让 poll 循环处理
            fixed += 1  # poll 循环会自动处理 transcribed=1 的
        elif job_status.get("status") == "error":
            db.execute(
                "UPDATE recordings SET transcribed=-1, transcribe_error=? WHERE id=?",
                (job_status.get("error", "GPU job failed")[:200], r["id"])
            )
            fixed += 1
    
    db.commit()
    db.close()
    # 只返回实际操作的计数，total 不再混入 reset
    return {"fixed": fixed, "reset": reset, "checked": len(rows)}

def fix_stuck_pipelines():
    """修复卡在 status=1 的导演版/自编版（仅当运行超过 4 小时才重置）"""
    import time
    db = sqlite3.connect(DB_PATH, timeout=30)
    
    # 只重置运行超过 4 小时的 pipeline，避免中断正常运行的任务
    four_hours_ago = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 4*3600))
    
    director_rows = db.execute(
        "SELECT id FROM clip_groups WHERE director_status = 1 AND created_at < ?", (four_hours_ago,)
    ).fetchall()
    
    creative_rows = db.execute(
        "SELECT id FROM clip_groups WHERE creative_status = 1 AND created_at < ?", (four_hours_ago,)
    ).fetchall()
    
    director_reset = 0
    creative_reset = 0
    
    if director_rows:
        for row in director_rows:
            db.execute("UPDATE clip_groups SET director_status = 0 WHERE id = ? AND director_status = 1", (row[0],))
            director_reset += 1
    
    if creative_rows:
        for row in creative_rows:
            db.execute("UPDATE clip_groups SET creative_status = 0 WHERE id = ? AND creative_status = 1", (row[0],))
            creative_reset += 1
    
    db.commit()
    db.close()
    return {"director_reset": director_reset, "creative_reset": creative_reset, "director_checked": len(director_rows), "creative_checked": len(creative_rows)}

def restart_backend():
    """重启后端以触发 backfill（通过 kill+reexec，保持 --workers 1）"""
    # Find the backend process
    try:
        result = subprocess.run(
            ["pgrep", "-f", "uvicorn main:app.*--port 8899"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            pids = result.stdout.strip().split("\n")
            for pid_str in pids:
                pid = int(pid_str)
                # Don't kill ourselves
                if pid != os.getpid():
                    os.kill(pid, 15)  # SIGTERM
                    print(f"Sent SIGTERM to backend PID {pid}")
            time.sleep(3)
            # Verify it's gone
            alive = subprocess.run(
                ["pgrep", "-f", "uvicorn main:app.*--port 8899"],
                capture_output=True, text=True, timeout=5
            )
            if alive.returncode != 0:
                print("Backend stopped, restarting...")
                # Restart via nohup
                backend_dir = "/Users/claw/work/douyin-recorder/backend"
                subprocess.Popen(
                    ["/opt/homebrew/Cellar/python@3.11/3.11.15/Frameworks/Python.framework/Versions/3.11/Resources/Python.app/Contents/MacOS/Python",
                     "/opt/homebrew/bin/uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8899"],
                    cwd=backend_dir,
                    stdout=open(os.path.join(backend_dir, "backend_run.log"), "a"),
                    stderr=subprocess.STDOUT,
                    start_new_session=True
                )
                time.sleep(5)
                print("Backend restarted")
            else:
                print("Backend still running, trying SIGKILL...")
                for pid_str in pids:
                    pid = int(pid_str)
                    if pid != os.getpid():
                        os.kill(pid, 9)
                time.sleep(3)
                backend_dir = "/Users/claw/work/douyin-recorder/backend"
                subprocess.Popen(
                    ["/opt/homebrew/Cellar/python@3.11/3.11.15/Frameworks/Python.framework/Versions/3.11/Resources/Python.app/Contents/MacOS/Python",
                     "/opt/homebrew/bin/uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8899"],
                    cwd=backend_dir,
                    stdout=open(os.path.join(backend_dir, "backend_run.log"), "a"),
                    stderr=subprocess.STDOUT,
                    start_new_session=True
                )
                time.sleep(5)
                print("Backend restarted (after SIGKILL)")
        else:
            print("No backend process found")
    except Exception as e:
        print(f"Backend restart failed: {e}")

def main():
    report = []
    actions_taken = []
    state = load_state()
    
    # 1. 检查 GPU 状态
    gpu_health = get_gpu_health()
    if "error" in gpu_health:
        report.append(f"❌ GPU 服务不可达: {gpu_health['error']}")
        # 尝试通过 watchdog 重启
        wd = get_watchdog_status()
        if "error" not in wd:
            restart_gpu_service()
            actions_taken.append("🔄 通过 Watchdog 重启了 GPU 服务")
        save_state(state)
        print("\n".join(report + actions_taken))
        return 1
    
    gpu_3d = gpu_health.get("gpu_3d_pct", 0)
    queue_depth = gpu_health.get("queue_depth", 0)
    gpu_busy = gpu_health.get("gpu_busy", False)
    
    report.append(f"📊 GPU 状态: 3D={gpu_3d}%, queue={queue_depth}, busy={gpu_busy}")
    
    # 2. 获取作业统计
    db_stats = get_db_stats()
    report.append(f"📋 转录: waiting_gpu={db_stats['transcribed_waiting']}, ready_upload={db_stats['transcribed_ready']}")
    report.append(f"📋 导演版: pending={db_stats['director_pending']}, running={db_stats['director_running']}")
    report.append(f"📋 自编版: pending={db_stats['creative_pending']}, running={db_stats['creative_running']}")
    
    has_backlog = (
        db_stats["transcribed_waiting"] > 5 or
        db_stats["transcribed_ready"] > 5 or
        db_stats["director_pending"] > 0 or
        db_stats["creative_pending"] > 0
    )
    
    # 3. 检查 GPU 是否持续空闲
    # 注意：whisper 转录使用 CUDA compute 而非 3D 渲染，gpu_3d_pct 始终为 0%
    # 因此必须结合 gpu_busy 和 queue_depth 来判断真正空闲
    if gpu_3d < LOW_GPU_THRESHOLD and not gpu_busy and queue_depth < 100:
        # 3D 低 + 不忙 + 队列浅 → 真正空闲
        state["low_gpu_count"] = state.get("low_gpu_count", 0) + 1
    else:
        state["low_gpu_count"] = 0
    
    gpu_idle_prolonged = state["low_gpu_count"] >= LOW_GPU_CONSECUTIVE
    
    if gpu_idle_prolonged and has_backlog:
        report.append(f"⚠️ GPU 空闲超 {state['low_gpu_count']*5} 分钟，但有作业积压！")
        
        # 4. 修复卡住的转录
        if db_stats["stuck_transcriptions"] > 0:
            fix_result = fix_stuck_transcriptions()
            actions_taken.append(f"🔧 修复转录: {fix_result}")
        
        # 5. 修复卡住的 pipeline
        pipeline_fix = fix_stuck_pipelines()
        if pipeline_fix["director_reset"] > 0 or pipeline_fix["creative_reset"] > 0:
            actions_taken.append(f"🔧 重置 pipeline: {pipeline_fix}")
        
        # 6. 如果 GPU 队列空且有积压，可能需要重启
        last_restart = state.get("last_restart", 0)
        time_since_restart = time.time() - last_restart
        
        # Only restart backend if it hasn't been restarted in the last 30 minutes.
        # Frequent restarts break the backfill's stagger loop (405 groups × 2s = 13.5min).
        BACKEND_RESTART_COOLDOWN = 1800  # 30 minutes
        
        if queue_depth == 0 and not gpu_busy and time_since_restart > BACKEND_RESTART_COOLDOWN:
            # GPU 完全空闲，队列空，有积压 → 重启 GPU 服务 + 后端
            report.append("🔄 GPU 完全空闲且队列为空，执行重启...")
            
            # 重启 GPU 服务
            restart_result = restart_gpu_service()
            if "error" not in (restart_result or {}):
                actions_taken.append("🔄 重启 GPU 服务成功")
            else:
                actions_taken.append(f"❌ GPU 重启失败: {restart_result}")
            
            time.sleep(5)
            
            # 重启后端触发 backfill
            restart_backend()
            actions_taken.append("🔄 重启后端服务，触发 backfill")
            
            state["last_restart"] = time.time()
        elif queue_depth == 0 and not gpu_busy and time_since_restart <= BACKEND_RESTART_COOLDOWN:
            # 最近已重启过，只重启后端
            restart_backend()
            actions_taken.append("🔄 重启后端触发 backfill（GPU 最近已重启，跳过 GPU 重启）")
    elif gpu_idle_prolonged and not has_backlog:
        report.append("✅ GPU 空闲但无积压，正常待机")
        state["low_gpu_count"] = 0
    elif not gpu_idle_prolonged and has_backlog:
        report.append("✅ GPU 正在工作，有积压正在处理中")
    else:
        report.append("✅ 一切正常")
    
    save_state(state)
    
    # 输出报告
    output = "\n".join(report)
    if actions_taken:
        output += "\n\n### 自动修复操作\n" + "\n".join(actions_taken)
    
    print(output)
    
    # 如果有异常或有操作返回 1（触发通知）
    if actions_taken:
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
