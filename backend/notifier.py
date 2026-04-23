"""
notifier.py — 通过 OpenClaw system event 发送运维通知
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

OPENCLAW_CMD = "/opt/homebrew/bin/openclaw"


async def notify(text: str) -> None:
    """异步发送 OpenClaw 通知，失败时只记录日志，不抛异常"""
    try:
        proc = await asyncio.create_subprocess_exec(
            OPENCLAW_CMD, "system", "event",
            "--text", text,
            "--mode", "now",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=10)
    except Exception as e:
        logger.warning(f"[notifier] 通知发送失败（不影响主流程）: {e}")
