"""
Background publish scheduler.
Polls every 60 seconds for pending/scheduled publish tasks and executes them.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Callable, Optional

import aiosqlite

from db import DB_PATH

logger = logging.getLogger(__name__)

RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), "..", "recordings")
COOKIES_DIR = os.path.expanduser("~/.douyin-publisher/cookies")


def _get_publisher(platform: str):
    if platform == "douyin":
        from publisher_douyin import DouyinPublisher
        return DouyinPublisher()
    if platform == "kuaishou":
        from publisher_kuaishou import KuaishouPublisher
        return KuaishouPublisher()
    if platform == "xiaohongshu":
        from publisher_xiaohongshu import XiaohongshuPublisher
        return XiaohongshuPublisher()
    if platform == "bilibili":
        from publisher_bilibili import BilibiliPublisher
        return BilibiliPublisher()
    raise ValueError(f"Unknown platform: {platform}")


async def _execute_task(task: dict, broadcast_fn: Optional[Callable] = None):
    task_id = task["id"]
    platform = task["platform"]

    async def _set_status(status: str, error_msg: str = None, published_at: str = None):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """UPDATE publish_tasks SET status = ?, error_msg = ?, published_at = ?
                   WHERE id = ?""",
                (status, error_msg, published_at, task_id),
            )
            await db.commit()
        if broadcast_fn:
            await broadcast_fn({
                "type": "publish_task_update",
                "task_id": task_id,
                "status": status,
                "error_msg": error_msg,
            })

    await _set_status("publishing")

    try:
        publisher = _get_publisher(platform)

        # Resolve video path
        video_path = task.get("video_path")
        if not video_path and task.get("merged_filename"):
            video_path = os.path.join(RECORDINGS_DIR, task["merged_filename"])
        if not video_path or not os.path.exists(video_path):
            raise RuntimeError(f"Video file not found: {video_path}")

        # Build task context
        task_ctx = dict(task)
        if task.get("cookie_file"):
            task_ctx["_cookie_file"] = task["cookie_file"]

        async def _progress(message: str):
            if broadcast_fn:
                await broadcast_fn({"type": "publish_progress", "task_id": task_id, "message": message})
        task_ctx["_progress_fn"] = _progress

        # Resolve product links (product_url preferred, fallback to product_id)
        product_links: list[str] = []
        if task.get("product_ids"):
            ids = [int(x) for x in str(task["product_ids"]).split(",") if x.strip()]
            if ids:
                placeholders = ",".join("?" * len(ids))
                async with aiosqlite.connect(DB_PATH) as pdb:
                    pdb.row_factory = aiosqlite.Row
                    async with pdb.execute(
                        f"SELECT product_url, product_id FROM products WHERE id IN ({placeholders})", ids
                    ) as cur:
                        for r in await cur.fetchall():
                            link = r["product_url"] or r["product_id"]
                            if link:
                                product_links.append(link)
        elif task.get("product_douyin_id"):
            product_links = [task["product_douyin_id"]]
        if product_links:
            task_ctx["_product_douyin_ids"] = product_links

        url = await publisher.publish(task_ctx, video_path)
        published_at = datetime.now(timezone.utc).isoformat()
        await _set_status("done", published_at=published_at)
        logger.info(f"Task {task_id} published: {url}")

    except Exception as e:
        logger.error(f"Task {task_id} failed: {e}")
        await _set_status("failed", error_msg=str(e)[:500])


async def _reset_stuck_publishing_tasks():
    """On startup, reset any tasks stuck in 'publishing' to 'failed' (server was killed mid-publish)."""
    async with aiosqlite.connect(DB_PATH) as db:
        result = await db.execute(
            "UPDATE publish_tasks SET status='failed', error_msg='服务重启时任务中断，请重试' WHERE status='publishing'"
        )
        await db.commit()
        if result.rowcount:
            logger.warning(f"Reset {result.rowcount} stuck 'publishing' task(s) to 'failed'")


async def poll_publish_tasks(broadcast_fn: Optional[Callable] = None, interval: int = 60):
    """Continuously poll and execute due publish tasks."""
    logger.info("Publish scheduler started")
    await _reset_stuck_publishing_tasks()
    while True:
        try:
            now = datetime.now(timezone.utc).isoformat()
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                # pending (immediate) + scheduled (due now)
                async with db.execute(
                    """SELECT t.*,
                              g.merged_filename,
                              pa.cookie_file,
                              p.product_id as product_douyin_id
                       FROM publish_tasks t
                       JOIN clip_groups g ON t.group_id = g.id
                       LEFT JOIN publish_accounts pa ON t.account_id = pa.id
                       LEFT JOIN products p ON t.product_id = p.id
                       WHERE t.status IN ('pending', 'scheduled')
                         AND (t.scheduled_at IS NULL OR t.scheduled_at <= ?)
                    """,
                    (now,),
                ) as cur:
                    tasks = await cur.fetchall()

            for task in tasks:
                asyncio.create_task(_execute_task(dict(task), broadcast_fn))

        except Exception as e:
            logger.error(f"Scheduler poll error: {e}")

        await asyncio.sleep(interval)
