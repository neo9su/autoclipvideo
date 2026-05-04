"""
Background publish scheduler.
Polls every 60 seconds for pending/scheduled publish tasks and executes them.
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Callable, Optional

import aiosqlite

from db import DB_PATH, aio_connect
from notifier import notify

logger = logging.getLogger(__name__)

RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), "..", "recordings")
COOKIES_DIR = os.path.expanduser("~/.douyin-publisher/cookies")


async def check_video_quality(video_path: str) -> tuple[bool, str]:
    """
    Check video quality requirements for publishing:
      - Resolution >= 1080x1920 (portrait 1080P)
      - Frame rate >= 25 fps
      - Duration >= 30 seconds
    Returns (passed, reason). reason is empty string if passed.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", "-show_format", video_path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return False, "ffprobe 无法读取视频文件"
        info = json.loads(stdout)
    except Exception as e:
        return False, f"视频信息读取失败: {e}"

    video_stream = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    if not video_stream:
        return False, "视频文件中未找到视频流"

    issues = []

    # Resolution: both dimensions must meet 1080x1920
    w = int(video_stream.get("width", 0))
    h = int(video_stream.get("height", 0))
    long_side, short_side = max(w, h), min(w, h)
    if short_side < 1080 or long_side < 1920:
        issues.append(f"分辨率不足（{w}x{h}，需要 1080x1920 以上）")

    # Frame rate: parse "num/den" fraction
    fps_raw = video_stream.get("r_frame_rate", "0/1")
    try:
        num, den = fps_raw.split("/")
        fps = float(num) / float(den)
    except Exception:
        fps = 0.0
    if fps < 25:
        issues.append(f"帧率不足（{fps:.1f} fps，需要 ≥ 25 fps）")

    # Duration: from format section (more reliable than stream duration)
    try:
        duration = float(info.get("format", {}).get("duration", 0))
    except Exception:
        duration = 0.0
    if duration < 30:
        issues.append(f"时长不足（{duration:.1f}s，需要 ≥ 30 秒）")

    if issues:
        return False, "；".join(issues)
    return True, ""


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
        async with aio_connect() as db:
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

        # Quality gate: resolution, fps, duration
        passed, quality_reason = await check_video_quality(video_path)
        if not passed:
            # Mark the group so it shows in management UI
            group_id = task.get("group_id")
            if group_id:
                async with aio_connect() as db:
                    await db.execute(
                        "UPDATE clip_groups SET quality_issue = ? WHERE id = ?",
                        (quality_reason, group_id),
                    )
                    await db.commit()
            raise RuntimeError(f"视频质量不达标，请重新剪辑：{quality_reason}")

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
        product_names: list[str] = []
        product_ids_str = task.get("product_ids")
        if product_ids_str:
            ids = [int(x) for x in str(product_ids_str).split(",") if x.strip()]
            if ids:
                placeholders = ",".join("?" * len(ids))
                async with aio_connect() as pdb:
                    pdb.row_factory = aiosqlite.Row
                    async with pdb.execute(
                        f"SELECT product_url, product_id, product_name FROM products WHERE id IN ({placeholders})", ids
                    ) as cur:
                        for r in await cur.fetchall():
                            link = r["product_url"] or r["product_id"]
                            if link:
                                product_links.append(link)
                                product_names.append(r["product_name"] or "")
        elif task.get("product_douyin_id"):
            product_links = [task["product_douyin_id"]]
            product_names = [""]
        if product_links and not task.get("no_cart"):
            task_ctx["_product_douyin_ids"] = product_links
            task_ctx["_product_names"] = product_names

        url = await publisher.publish(task_ctx, video_path)
        published_at = datetime.now(timezone.utc).isoformat()
        await _set_status("done", published_at=published_at)
        logger.info(f"Task {task_id} published: {url}")
        title = task.get("title") or f"任务#{task_id}"
        asyncio.create_task(notify(f"✅ 抖音发布成功：{title}"))

    except Exception as e:
        err_msg = str(e)
        logger.error(f"Task {task_id} failed: {err_msg}")
        # 不可重试的错误类型
        non_retryable = ["视频质量不达标", "Video file not found", "video file not found",
                          "Not logged in", "login QR code", "Cookie may have expired",
                          "Re-login timed out"]  # 扫码等待超时，不重试（需要手动处理）
        is_retryable = not any(kw in err_msg for kw in non_retryable)
        retry_count = task.get("retry_count", 0) or 0
        if is_retryable and retry_count < 2:
            new_retry = retry_count + 1
            logger.info(f"Task {task_id} will retry ({new_retry}/2) in 30s")
            await asyncio.sleep(30)
            async with aio_connect() as db:
                await db.execute(
                    "UPDATE publish_tasks SET status='pending', retry_count=?, error_msg=? WHERE id=?",
                    (new_retry, f"[重试{new_retry}/2] {err_msg[:400]}", task_id),
                )
                await db.commit()
        else:
            await _set_status("failed", error_msg=err_msg[:500])
            title = task.get("title") or f"任务#{task_id}"
            retry_info = f"（已重试{retry_count}次）" if retry_count > 0 else ""
            # Cookie 失效 / 扫码超时：提示重新登录
            if any(kw in err_msg for kw in ["Not logged in", "login QR", "Re-login timed out", "Cookie may have expired"]):
                asyncio.create_task(notify(
                    f"🔐 抖音 Cookie 已失效！请尽快重新登录抖音创作者中心\n"
                    f"任务「{title}」已暂停，重新登录后可直接重试"
                ))
            else:
                asyncio.create_task(notify(
                    f"🚨 抖音发布失败{retry_info}：{title}\n原因：{err_msg[:200]}"
                ))


async def _reset_stuck_publishing_tasks():
    """On startup, reset any tasks stuck in 'publishing' to 'failed' (server was killed mid-publish)."""
    async with aio_connect() as db:
        result = await db.execute(
            "UPDATE publish_tasks SET status='failed', error_msg='服务重启时任务中断，请重试' WHERE status='publishing'"
        )
        await db.commit()
        if result.rowcount:
            logger.warning(f"Reset {result.rowcount} stuck 'publishing' task(s) to 'failed'")


async def poll_publish_tasks(broadcast_fn: Optional[Callable] = None, interval: int = 90):
    """Continuously poll and execute due publish tasks (throttled for stability)."""
    logger.info("Publish scheduler started with throttling")
    await _reset_stuck_publishing_tasks()
    
    MAX_CONCURRENT = 1  # 限制为1个并发任务避免内存压力
    
    while True:
        try:
            # 检查当前正在发布的任务数量
            async with aio_connect() as db:
                async with db.execute(
                    "SELECT COUNT(*) FROM publish_tasks WHERE status = 'publishing'"
                ) as cur:
                    publishing_count = (await cur.fetchone())[0]
            
            if publishing_count >= MAX_CONCURRENT:
                logger.info(f"Already {publishing_count} tasks publishing, skipping this cycle")
                await asyncio.sleep(interval)
                continue
                
            # 获取待发布任务(限制数量)
            now = datetime.now(timezone.utc).isoformat()
            async with aio_connect() as db:
                db.row_factory = aiosqlite.Row
                # pending (immediate) + scheduled (due now) - 只取1个
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
                       LIMIT 1
                    """,
                    (now,),
                ) as cur:
                    tasks = await cur.fetchall()

            # ── 低活跃时段检查：00:00~07:00 期间跳过发布 ────────────────────
            _now_local = datetime.now()  # 本地时间
            _hour = _now_local.hour
            if 0 <= _hour < 7:
                logger.info(f"当前时间 {_hour:02d}:{_now_local.minute:02d}，处于低活跃时段（00:00-07:00），跳过本次调度")
                await asyncio.sleep(interval)
                continue
            # ────────────────────────────────────────────────────────────────────

            task_started = False
            for task in tasks:
                logger.info(f"Starting single task {task['id']}")
                asyncio.create_task(_execute_task(dict(task), broadcast_fn))
                task_started = True
                break  # 只处理一个任务

        except Exception as e:
            logger.error(f"Scheduler poll error: {e}")
            task_started = False

        # Smart sleep:
        # - If there are pending (immediate) tasks waiting → poll again in 5s
        # - If a scheduled task is due soon → wake up early
        # - Otherwise → full interval
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            async with aio_connect() as db:
                # Check for immediate pending tasks
                async with db.execute(
                    "SELECT COUNT(*) FROM publish_tasks WHERE status = 'pending' AND (scheduled_at IS NULL OR scheduled_at <= ?)",
                    (now_iso,),
                ) as cur:
                    pending_count = (await cur.fetchone())[0]

                if pending_count > 0 and publishing_count == 0 and not task_started:
                    # There are tasks ready to run right now — check again quickly
                    sleep_secs = 5
                else:
                    # Wake up early if a scheduled task is due soon
                    async with db.execute(
                        """SELECT scheduled_at FROM publish_tasks
                           WHERE status = 'scheduled' AND scheduled_at > ?
                           ORDER BY scheduled_at ASC LIMIT 1""",
                        (now_iso,),
                    ) as cur:
                        row = await cur.fetchone()
                    if row and row[0]:
                        next_dt = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
                        secs_until = (next_dt - datetime.now(timezone.utc)).total_seconds()
                        sleep_secs = max(5, min(interval, secs_until + 1))
                    else:
                        sleep_secs = interval
        except Exception:
            sleep_secs = interval

        await asyncio.sleep(sleep_secs)
