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
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    stats = {}
    
    # 转录积压
    stats["transcribed_waiting"] = db.execute(
        "SELECT count(*) as c FROM recordings WHERE transcribed = 1"
    ).fetchone()["c"]
    
    stats["transcribed_ready"] = db.execute(
        "SELECT count(*) as c FROM recordings WHERE synced=0 AND transcribed=0 AND local_deleted=0 AND end_time IS NOT NULL AND end_time != start_time"
    ).fetchone()["c"]
    
    # 导演版积压
    stats["director_pending"] = db.execute(
        "SELECT count(*) as c FROM clip_groups WHERE director_status = 0"
    ).fetchone()["c"]
    
    stats["director_running"] = db.execute(
        "SELECT count(*) as c FROM clip_groups WHERE director_status = 1"
    ).fetchone()["c"]
    
    # creative 积压
    stats["creative_pending"] = db.execute(
        "SELECT count(*) as c FROM clip_groups WHERE creative_status = 0"
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
    """修复卡住的转录作业：检查 GPU 上的状态，完成的拉回来"""
    db = sqlite3.connect(DB_PATH)
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
    return {"fixed": fixed, "reset": reset, "total": len(rows)}

def fix_stuck_pipelines():
    """修复卡在 status=1 的导演版/自编版"""
    db = sqlite3.connect(DB_PATH)
    
    director_stuck = db.execute(
        "SELECT count(*) FROM clip_groups WHERE director_status = 1"
    ).fetchone()[0]
    creative_stuck = db.execute(
        "SELECT count(*) FROM clip_groups WHERE creative_status = 1"
    ).fetchone()[0]
    
    if director_stuck > 0:
        db.execute("UPDATE clip_groups SET director_status = 0 WHERE director_status = 1")
    if creative_stuck > 0:
        db.execute("UPDATE clip_groups SET creative_status = 0 WHERE creative_status = 1")
    
    db.commit()
    db.close()
    return {"director_reset": director_stuck, "creative_reset": creative_stuck}

def restart_backend():
    """重启后端以触发 backfill"""
    subprocess.run(["kill", "-9"] + subprocess.run(
        ["lsof", "-ti:8899"], capture_output=True, text=True
    ).stdout.strip().split(), capture_output=True)
    time.sleep(2)
    subprocess.Popen(
        ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8899"],
        cwd="/Users/claw/work/douyin-recorder/backend",
        stdout=open("/private/tmp/douyin_backend.log", "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True
    )
    time.sleep(3)

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
    if gpu_3d < LOW_GPU_THRESHOLD:
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
        
        if queue_depth == 0 and not gpu_busy and time_since_restart > 3600:
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
        elif queue_depth == 0 and not gpu_busy and time_since_restart <= 3600:
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
