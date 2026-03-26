#!/usr/bin/env python3
"""
系统健康监控脚本 — 后台独立运行
每 5 分钟检查一次 GPU 服务、转录队列、增强任务、剪辑队列。
自动修复已知问题并写入 MONITOR_LOG.md；整点写入 PROJECT_SUMMARY.md；
本地 09:00 生成 MONITOR_BRIEFING.md。

用法:
    python health_monitor.py              # 前台运行（Ctrl+C 停止）
    python health_monitor.py --daemon     # 后台运行（nohup）
    python health_monitor.py --once       # 只跑一次检查
"""

import argparse
import asyncio
import datetime
import logging
import os
import subprocess
import sys

import httpx

BASE_URL = "http://localhost:8899"
WATCHDOG_URL = "http://10.190.0.203:8878"
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(PROJECT_DIR, "MONITOR_LOG.md")
SUMMARY_FILE = os.path.join(PROJECT_DIR, "PROJECT_SUMMARY.md")
BRIEFING_FILE = os.path.join(PROJECT_DIR, "MONITOR_BRIEFING.md")
MONITOR_LOG = os.path.join(PROJECT_DIR, "health_monitor.log")

INTERVAL_SECONDS = 300  # 5 分钟
SSH_KEY = os.path.expanduser("~/.ssh/id_ed25519")
GPU_HOST = "neo@10.190.0.203"
GPU_RESTART_CMD = 'cd C:/Users/neo/douyin_processor && python watchdog.py --restart-all'

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(MONITOR_LOG, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("health_monitor")

# 上次 last_submit_at 值，用于检测队列是否卡住
_last_submit_at_seen: str | None = None
_last_submit_at_changed_time: datetime.datetime | None = None


async def get(client: httpx.AsyncClient, path: str, timeout: float = 10.0) -> dict | None:
    try:
        r = await client.get(f"{BASE_URL}{path}", timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.debug(f"GET {path} failed: {e}")
    return None


async def post(client: httpx.AsyncClient, path: str, timeout: float = 10.0) -> bool:
    try:
        r = await client.post(f"{BASE_URL}{path}", timeout=timeout)
        return r.status_code == 200
    except Exception as e:
        logger.debug(f"POST {path} failed: {e}")
    return False


async def check_watchdog(client: httpx.AsyncClient) -> dict | None:
    try:
        r = await client.get(f"{WATCHDOG_URL}/status", timeout=8.0)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def ssh_restart_gpu() -> bool:
    try:
        result = subprocess.run(
            ["ssh", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no",
             "-o", "ConnectTimeout=10", GPU_HOST, GPU_RESTART_CMD],
            capture_output=True, text=True, timeout=30,
        )
        logger.info(f"SSH restart stdout: {result.stdout.strip()}")
        if result.returncode != 0:
            logger.warning(f"SSH restart stderr: {result.stderr.strip()}")
        return result.returncode == 0
    except Exception as e:
        logger.warning(f"SSH restart failed: {e}")
        return False


def append_log(line: str):
    ts = datetime.datetime.utcnow().strftime("%H:%M UTC")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"| {ts} | {line} |\n")


def append_summary(snapshot: str):
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M UTC")
    with open(SUMMARY_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n## 整点快照 {ts}\n\n{snapshot}\n")


def write_briefing():
    if not os.path.exists(LOG_FILE):
        return
    with open(LOG_FILE, encoding="utf-8") as f:
        content = f.read()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    briefing = f"# 监控简报 — {now}\n\n本文档由 health_monitor.py 在 09:00 本地时间自动生成。\n\n## 监控日志摘要\n\n{content}\n"
    with open(BRIEFING_FILE, "w", encoding="utf-8") as f:
        f.write(briefing)
    logger.info(f"Briefing written to {BRIEFING_FILE}")


async def run_check():
    global _last_submit_at_seen, _last_submit_at_changed_time

    issues = []
    actions = []

    async with httpx.AsyncClient() as client:
        # 1. GPU 状态
        gpu = await get(client, "/api/gpu/status")
        if gpu is None:
            issues.append("GPU API 不可达")
            logger.warning("GPU API unreachable, attempting SSH restart")
            ok = ssh_restart_gpu()
            actions.append(f"SSH重启{'成功' if ok else '失败'}")
        else:
            pending = gpu.get("pending_transcribe", 0)
            gpu_busy = gpu.get("gpu_busy", False)
            queue_depth = gpu.get("queue_depth", 0)
            last_submit = gpu.get("last_submit_at", "")
            active_job = gpu.get("active_job_id", "-")

            logger.info(
                f"GPU: pending={pending} busy={gpu_busy} queue={queue_depth} "
                f"last_submit={last_submit} active={active_job}"
            )

            # 检测队列卡住：pending>0 且 gpu_busy=False 且 last_submit_at 超过 10 分钟未变
            now = datetime.datetime.utcnow()
            if last_submit != _last_submit_at_seen:
                _last_submit_at_seen = last_submit
                _last_submit_at_changed_time = now

            stale_minutes = 0
            if _last_submit_at_changed_time:
                stale_minutes = (now - _last_submit_at_changed_time).total_seconds() / 60

            if pending > 0 and not gpu_busy and stale_minutes > 10:
                issues.append(f"队列卡住(pending={pending}, {stale_minutes:.0f}min无提交)")
                logger.warning("Queue stuck, flushing...")
                ok = await post(client, "/api/transcribe/flush")
                actions.append(f"flush{'成功' if ok else '失败'}")

            # 2. Watchdog
            wd = await check_watchdog(client)
            if wd is None:
                issues.append("Watchdog不可达")
            else:
                restart_count = wd.get("restart_count", 0)
                uptime = wd.get("uptime_seconds", 0)
                logger.info(f"Watchdog: restart_count={restart_count} uptime={uptime}s")

            # 3. Enhance jobs
            enhance = await get(client, "/api/enhance/jobs")
            if enhance is not None:
                jobs = enhance if isinstance(enhance, list) else enhance.get("jobs", [])
                error_jobs = [j for j in jobs if j.get("status") == "error"]
                if error_jobs:
                    issues.append(f"Enhance错误任务={len(error_jobs)}")
                    logger.warning(f"Enhance error jobs: {[j.get('job_id') for j in error_jobs]}")

            # 4. Clip 队列
            clips = await get(client, "/api/clips/queue")
            if clips is not None:
                running = clips.get("running", 0)
                queued = clips.get("queued", 0)
                logger.info(f"Clips: running={running} queued={queued}")

            # 写日志行
            status_str = (
                f"pending={pending} gpu_busy={gpu_busy} queue={queue_depth}"
            )
            issue_str = "; ".join(issues) if issues else "正常"
            action_str = "; ".join(actions) if actions else "-"
            append_log(f"{status_str} | {issue_str} | {action_str}")

    # 整点快照
    now_local = datetime.datetime.now()
    if now_local.minute < 6 and gpu is not None:  # 整点后 5 分钟内触发
        snapshot = (
            f"- pending_transcribe: {pending}\n"
            f"- gpu_busy: {gpu_busy}\n"
            f"- queue_depth: {queue_depth}\n"
            f"- last_submit_at: {last_submit}\n"
            f"- issues: {issue_str}\n"
        )
        append_summary(snapshot)

    # 09:00 本地时间生成简报
    if now_local.hour == 9 and now_local.minute < 6:
        write_briefing()


async def main_loop():
    logger.info("health_monitor started (interval=5min)")
    # 追加表头（如文件不存在）
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.write("# 系统监控日志\n\n| UTC时间 | 状态 | 问题 | 操作 |\n|---------|------|------|------|\n")

    while True:
        try:
            await run_check()
        except Exception as e:
            logger.error(f"Check failed: {e}", exc_info=True)
        await asyncio.sleep(INTERVAL_SECONDS)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="只执行一次检查后退出")
    parser.add_argument("--daemon", action="store_true", help="以后台进程运行（重定向日志到文件）")
    args = parser.parse_args()

    if args.daemon:
        # 用 subprocess 在后台重启自身（不带 --daemon）
        log_fd = open(MONITOR_LOG, "a")
        proc = subprocess.Popen(
            [sys.executable, os.path.abspath(__file__)],
            stdout=log_fd, stderr=log_fd,
            start_new_session=True,
        )
        print(f"health_monitor started in background, PID={proc.pid}")
        print(f"Log: {MONITOR_LOG}")
        sys.exit(0)

    if args.once:
        asyncio.run(run_check())
    else:
        asyncio.run(main_loop())


if __name__ == "__main__":
    main()
