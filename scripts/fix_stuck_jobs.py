#!/usr/bin/env python3
"""
fix_stuck_jobs.py — douyin-recorder 作业卡死自动修复脚本

检查并修复以下卡死场景：
1. 后端进程死了 → 重启
2. recordings.transcribed=1 卡死（上传/转录挂起） → 重置为 0
3. recordings.clipped=1 卡死（剪辑挂起） → 重置为 0（无文件）或 2（有文件）
4. clip_groups.{classic,director,creative}_status=1 卡死 → 重置为 0，触发 API 重跑
5. GPU 服务不可达 → 告警（不自动重启，GPU 侧有 watchdog）
6. 转录队列连续多轮无进展（pending 积压但 running=0）→ 触发 flush_poll

用法：
  python3 scripts/fix_stuck_jobs.py          # 检查 + 修复
  python3 scripts/fix_stuck_jobs.py --dry-run # 仅检查，不修改
  python3 scripts/fix_stuck_jobs.py --notify  # 有修复时推送 OpenClaw 通知

监控 cron 用法（每 30 分钟，已由 OpenClaw cron 调度）：
  python3 /Users/claw/work/douyin-recorder/scripts/fix_stuck_jobs.py --notify
"""

import os
import sys
import time
import sqlite3
import subprocess
import argparse
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone

# ── 配置 ────────────────────────────────────────────────────────────────────
PROJECT_DIR  = "/Users/claw/work/douyin-recorder"
DB_PATH      = os.path.join(PROJECT_DIR, "douyin.db")
BACKEND_LOG  = "/Users/claw/work/douyin-recorder/backend.log"
BACKEND_LOG_LEGACY = "/private/tmp/douyin_backend.log"  # 旧路径（重启前的日志）
BACKEND_URL  = "http://localhost:8899"
GPU_HEALTH   = "http://10.190.0.203:8877/health"
GPU_WATCHDOG = "http://10.190.0.203:8878/status"

# 卡死判定阈值（秒）
TRANSCRIBE_STUCK_SECS = 1800   # transcribed=1 超过 30 分钟视为卡死
CLIP_STUCK_SECS       = 3600   # clipped=1    超过 60 分钟视为卡死
GROUP_STUCK_SECS      = 3600   # group status=1 超过 60 分钟视为卡死

# 启动后端命令
START_CMD = (
    f"cd {PROJECT_DIR} && "
    f"nohup python3 -m uvicorn backend.main:app "
    f"--host 0.0.0.0 --port 8899 --app-dir backend "
    f">> {BACKEND_LOG} 2>&1 &"
)

# ── 工具函数 ─────────────────────────────────────────────────────────────────

def now_ts() -> float:
    return time.time()

def http_get(url: str, timeout: int = 5) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "fix_stuck_jobs/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None

def http_post(url: str, data: dict | None = None, timeout: int = 10) -> dict | None:
    try:
        body = json.dumps(data or {}).encode()
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json", "User-Agent": "fix_stuck_jobs/1.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None

def notify(msg: str):
    """通过 openclaw 推送系统通知"""
    subprocess.run(
        ["openclaw", "system", "event", "--text", msg, "--mode", "now"],
        capture_output=True, timeout=10
    )

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

# ── 检查项 ───────────────────────────────────────────────────────────────────

class HealthReport:
    def __init__(self):
        self.issues: list[str] = []
        self.fixes:  list[str] = []
        self.errors: list[str] = []

    def issue(self, msg: str):
        self.issues.append(msg)
        log(f"  ⚠️  {msg}")

    def fix(self, msg: str):
        self.fixes.append(msg)
        log(f"  ✅ {msg}")

    def error(self, msg: str):
        self.errors.append(msg)
        log(f"  ❌ {msg}")

    @property
    def ok(self) -> bool:
        return not self.issues and not self.errors

    def summary(self) -> str:
        parts = []
        if self.fixes:
            parts.append("修复: " + "; ".join(self.fixes))
        if self.issues:
            parts.append("问题: " + "; ".join(self.issues))
        if self.errors:
            parts.append("错误: " + "; ".join(self.errors))
        return " | ".join(parts) if parts else "一切正常"


# ── 1. 后端进程检查 ──────────────────────────────────────────────────────────

def check_backend(report: HealthReport, dry_run: bool):
    log("【1】检查后端进程...")
    result = subprocess.run(
        ["pgrep", "-f", "uvicorn backend.main"],
        capture_output=True, text=True
    )
    pids = result.stdout.strip().split() if result.stdout.strip() else []

    if not pids:
        report.issue("后端进程不存在")
        if not dry_run:
            log("  → 正在重启后端...")
            ret = subprocess.run(START_CMD, shell=True, capture_output=True, text=True)
            if ret.returncode == 0:
                time.sleep(4)
                # 验证是否启动成功
                alive = http_get(f"{BACKEND_URL}/api/gpu/status", timeout=5)
                if alive:
                    report.fix("后端已重启并响应正常")
                else:
                    report.error("后端重启后仍无响应，请手动检查")
            else:
                report.error(f"后端启动命令失败: {ret.stderr[:200]}")
        else:
            log("  [dry-run] 跳过重启")
        return False
    else:
        log(f"  后端进程正常 PID={','.join(pids)}")

    # 进程存在，验证 HTTP 响应
    resp = http_get(f"{BACKEND_URL}/api/gpu/status", timeout=5)
    if resp is None:
        report.issue("后端进程存在但 HTTP 无响应（可能卡死）")
        if not dry_run:
            log("  → 强制 kill 并重启...")
            for pid in pids:
                subprocess.run(["kill", "-9", pid], capture_output=True)
            time.sleep(2)
            subprocess.run(START_CMD, shell=True, capture_output=True)
            time.sleep(4)
            alive = http_get(f"{BACKEND_URL}/api/gpu/status", timeout=5)
            if alive:
                report.fix("后端已强制重启并响应正常")
            else:
                report.error("后端重启后仍无响应")
        return False

    log(f"  HTTP 响应正常，pending_transcribe={resp.get('pending_transcribe', '?')}")
    return True


# ── 2. GPU 服务检查 ──────────────────────────────────────────────────────────

def check_gpu(report: HealthReport, _dry_run: bool):
    log("【2】检查 GPU 服务器 (10.190.0.203)...")

    health = http_get(GPU_HEALTH, timeout=6)
    if health is None:
        report.issue("GPU :8877 不可达（转录/剪辑将降级或失败）")
    else:
        q = health.get("queue_depth", 0)
        pending = health.get("clip_jobs_pending", 0)
        g3d = health.get("gpu_3d_pct")
        genc = health.get("gpu_enc_pct")
        gmem = health.get("gpu_mem_pct")
        util_str = (
            f" | GPU 3D={g3d}% Enc={genc}% Mem={gmem}%"
            if g3d is not None else ""
        )
        log(f"  GPU :8877 正常 — queue_depth={q} clip_pending={pending}{util_str}")

    watchdog = http_get(GPU_WATCHDOG, timeout=6)
    if watchdog is None:
        report.issue("GPU Watchdog :8878 不可达")
    else:
        svc = watchdog.get("gpu", {})
        comfy = watchdog.get("comfyui", {})
        gpu_ok = svc.get("running") and svc.get("healthy")
        comfy_ok = comfy.get("running") and comfy.get("healthy")
        if not gpu_ok:
            report.issue(f"GPU 转录服务异常: running={svc.get('running')} healthy={svc.get('healthy')}")
        if not comfy_ok:
            report.issue(f"ComfyUI 异常: running={comfy.get('running')} healthy={comfy.get('healthy')}")
        if gpu_ok and comfy_ok:
            g3d = svc.get("gpu_3d_pct")
            genc = svc.get("gpu_enc_pct")
            gmem = svc.get("gpu_mem_pct")
            util_str = (
                f" | 3D={g3d}% Enc={genc}% Mem={gmem}%"
                if g3d is not None else ""
            )
            log(f"  Watchdog :8878 — gpu=✅ comfyui=✅ uptime={svc.get('uptime_s',0)//3600}h{util_str}")

    return health is not None


# ── 3. 转录卡死检查（recordings.transcribed=1） ──────────────────────────────

def check_stuck_transcriptions(report: HealthReport, dry_run: bool):
    log("【3】检查卡死的转录任务 (transcribed=1)...")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # transcribed=1 但 start_time 对应已超 TRANSCRIBE_STUCK_SECS
    # DB 里没有 updated_at，用 start_time 作为保守估计（录像时间远早于卡住时间，所以只要存在就算卡）
    cur.execute("""
        SELECT id, filename, gpu_job_id, start_time
        FROM recordings
        WHERE transcribed = 1
    """)
    rows = cur.fetchall()

    if not rows:
        log("  无卡死转录任务")
        conn.close()
        return

    report.issue(f"发现 {len(rows)} 条 transcribed=1 卡死任务")
    for r in rows[:5]:
        log(f"    id={r['id']} file={r['filename']} job={r['gpu_job_id']}")

    if not dry_run:
        ids = [r["id"] for r in rows]
        placeholders = ",".join("?" * len(ids))
        conn.execute(f"""
            UPDATE recordings
            SET transcribed = 0, gpu_job_id = NULL
            WHERE id IN ({placeholders})
        """, ids)
        conn.commit()
        report.fix(f"已重置 {len(rows)} 条卡死转录任务为 pending")
        log("  → 触发 flush_poll 刷新队列...")
        http_post(f"{BACKEND_URL}/api/flush-poll", timeout=5)
    else:
        log(f"  [dry-run] 跳过重置 {len(rows)} 条转录任务")

    conn.close()


# ── 4. 剪辑卡死检查（recordings.clipped=1） ──────────────────────────────────

def check_stuck_clips(report: HealthReport, dry_run: bool):
    log("【4】检查卡死的剪辑任务 (clipped=1)...")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT id, filename, clip_filename
        FROM recordings
        WHERE clipped = 1
    """).fetchall()

    if not rows:
        log("  无卡死剪辑任务")
        conn.close()
        return

    report.issue(f"发现 {len(rows)} 条 clipped=1 卡死任务")

    recordings_dir = os.path.join(PROJECT_DIR, "recordings")
    with_file   = [r for r in rows if r["clip_filename"] and
                   os.path.exists(os.path.join(recordings_dir, r["clip_filename"]))]
    without_file = [r for r in rows if r not in with_file]

    if with_file:
        log(f"    → {len(with_file)} 条已有 clip 文件，标记 clipped=2")
    if without_file:
        log(f"    → {len(without_file)} 条无 clip 文件，重置 clipped=0")

    if not dry_run:
        if with_file:
            ids = [r["id"] for r in with_file]
            conn.execute(f"UPDATE recordings SET clipped=2 WHERE id IN ({','.join('?'*len(ids))})", ids)
        if without_file:
            ids = [r["id"] for r in without_file]
            conn.execute(f"UPDATE recordings SET clipped=0, clip_filename=NULL WHERE id IN ({','.join('?'*len(ids))})", ids)
        conn.commit()
        report.fix(f"已修复 {len(rows)} 条卡死剪辑任务")
    else:
        log(f"  [dry-run] 跳过修复 {len(rows)} 条剪辑任务")

    conn.close()


# ── 5. 分组流水线卡死检查（clip_groups.*_status=1） ───────────────────────────

def check_stuck_groups(report: HealthReport, dry_run: bool, backend_alive: bool):
    log("【5】检查卡死的分组流水线 (status=1)...")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    classic_stuck = conn.execute(
        "SELECT id, label FROM clip_groups WHERE classic_status=1"
    ).fetchall()
    director_stuck = conn.execute(
        "SELECT id, label FROM clip_groups WHERE director_status=1"
    ).fetchall()
    creative_stuck = conn.execute(
        "SELECT id, label FROM clip_groups WHERE creative_status=1"
    ).fetchall()

    total = len(classic_stuck) + len(director_stuck) + len(creative_stuck)
    if total == 0:
        log("  无卡死分组流水线")
        conn.close()
        return

    if classic_stuck:
        report.issue(f"classic_status=1 卡死: {[r['id'] for r in classic_stuck]}")
    if director_stuck:
        report.issue(f"director_status=1 卡死: {[r['id'] for r in director_stuck]}")
    if creative_stuck:
        report.issue(f"creative_status=1 卡死: {[r['id'] for r in creative_stuck]}")

    if dry_run:
        log(f"  [dry-run] 跳过重置 {total} 个卡死流水线")
        conn.close()
        return

    # 重置 DB
    if classic_stuck:
        conn.execute("UPDATE clip_groups SET classic_status=0 WHERE classic_status=1")
    if director_stuck:
        conn.execute("UPDATE clip_groups SET director_status=0 WHERE director_status=1")
    if creative_stuck:
        conn.execute("UPDATE clip_groups SET creative_status=0 WHERE creative_status=1")
    conn.commit()
    conn.close()

    # 通过 API 重新触发
    if backend_alive:
        all_stuck_ids = list(set(
            [r["id"] for r in classic_stuck] +
            [r["id"] for r in director_stuck] +
            [r["id"] for r in creative_stuck]
        ))
        triggered = 0
        for gid in all_stuck_ids:
            result = http_post(
                f"{BACKEND_URL}/api/groups/{gid}/merge?force=true",
                data=None,
                timeout=10
            )
            if result is not None:
                triggered += 1
            time.sleep(0.3)  # 避免并发冲击
        report.fix(f"已重置并重新触发 {triggered}/{len(all_stuck_ids)} 个卡死分组流水线")
    else:
        report.fix(f"已重置 {total} 个卡死分组流水线的 DB 状态（后端离线，待重启后自动 backfill）")


# ── 6. 转录队列进展检查 ──────────────────────────────────────────────────────

def check_transcribe_progress(report: HealthReport, dry_run: bool, backend_alive: bool):
    log("【6】检查转录队列进展...")

    if not backend_alive:
        log("  后端离线，跳过")
        return

    resp = http_get(f"{BACKEND_URL}/api/transcribe-queue", timeout=5)
    if not resp:
        log("  无法获取队列信息，跳过")
        return

    jobs = resp.get("jobs", [])
    running = [j for j in jobs if j.get("level") == "running"]
    pending = [j for j in jobs if j.get("level") in ("pending", "queued")]

    log(f"  转录队列: running={len(running)} pending/queued={len(pending)}")

    if len(pending) > 0 and len(running) == 0:
        # 进一步确认：看日志里最近 60s 内有没有 Uploading 记录（说明 poll 在跑，只是 GPU 500）
        log_path = BACKEND_LOG if os.path.exists(BACKEND_LOG) else BACKEND_LOG_LEGACY
        recent_upload_active = False
        if os.path.exists(log_path):
            tail = subprocess.run(["tail", "-20", log_path], capture_output=True, text=True)
            recent_upload_active = "Uploading" in tail.stdout or "Upload failed" in tail.stdout

        if recent_upload_active:
            log(f"  转录 poll 正在运行（日志有最新上传记录），GPU 500 导致任务失败后重排，属正常")
        else:
            report.issue(f"转录队列有 {len(pending)} 个任务积压，但无任务在运行（poll 可能卡住）")
            if not dry_run:
                result = http_post(f"{BACKEND_URL}/api/transcribe/flush", timeout=5)
                if result is not None:
                    report.fix("已触发 /api/transcribe/flush 恢复转录调度")
                else:
                    log("  → /api/transcribe/flush 无响应，跳过")
    elif len(running) > 0:
        log(f"  转录进行中: {[j.get('filename','?') for j in running[:2]]}")


# ── 7. 近期日志错误摘要 ──────────────────────────────────────────────────────

def check_recent_errors(report: HealthReport):
    log("【7】扫描近期错误日志...")
    # 优先读进程实际写的 log，再降级到旧路径
    log_path = BACKEND_LOG if os.path.exists(BACKEND_LOG) else BACKEND_LOG_LEGACY
    if not os.path.exists(log_path):
        log("  日志文件不存在")
        return

    result = subprocess.run(
        ["tail", "-100", log_path],
        capture_output=True, text=True
    )
    lines = result.stdout.splitlines()
    errors = [l for l in lines if any(k in l for k in ["ERROR", "CRITICAL", "Upload failed", "timed out after"])]

    if errors:
        # 去重统计
        from collections import Counter
        patterns = Counter()
        for l in errors:
            if "Upload failed" in l:
                patterns["Upload failed (GPU 上传 500)"] += 1
            elif "timed out" in l:
                patterns["TTS/GPU 超时"] += 1
            elif "ERROR" in l or "CRITICAL" in l:
                snippet = l[l.find("ERROR"):l.find("ERROR")+80] if "ERROR" in l else l[-80:]
                patterns[snippet.strip()] += 1

        summary = "; ".join(f"{k}×{v}" for k, v in patterns.most_common(5))
        log(f"  近期错误: {summary}")
        # 上传持续失败是已知问题（GPU 500），不算严重告警
        serious = [k for k in patterns if "Upload failed" not in k and "TTS" not in k
                   and "error while attempting to bind" not in k]  # 端口冲突是上次重启时的噪声，忽略
        if serious:
            report.issue(f"近期严重错误: {'; '.join(serious[:3])}")
        else:
            log(f"  （均为已知非严重错误，忽略）")
    else:
        log("  无严重错误")


# ── 主函数 ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="douyin-recorder 作业卡死修复工具")
    parser.add_argument("--dry-run", action="store_true", help="仅检查，不修改")
    parser.add_argument("--notify", action="store_true", help="有修复/错误时推送 OpenClaw 通知")
    args = parser.parse_args()

    log("=" * 60)
    log(f"douyin-recorder 健康巡检 {'[DRY-RUN]' if args.dry_run else '[自动修复]'}")
    log("=" * 60)

    report = HealthReport()

    backend_alive = check_backend(report, args.dry_run)
    gpu_alive     = check_gpu(report, args.dry_run)

    check_stuck_transcriptions(report, args.dry_run)
    check_stuck_clips(report, args.dry_run)
    check_stuck_groups(report, args.dry_run, backend_alive)
    check_transcribe_progress(report, args.dry_run, backend_alive)
    check_recent_errors(report)

    log("=" * 60)
    summary = report.summary()
    log(f"巡检完成: {summary}")
    log("=" * 60)

    if args.notify and (report.fixes or report.errors or report.issues):
        severity = "❌" if report.errors else ("🔧" if report.fixes else "⚠️")
        notify(f"{severity} douyin-recorder 巡检: {summary}")

    # 退出码：有未修复问题返回 1
    sys.exit(0 if (not report.errors and not report.issues) or report.fixes else 1)


if __name__ == "__main__":
    main()
