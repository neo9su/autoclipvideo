import asyncio
import logging
import os
from typing import Optional

import aiosqlite
import httpx

from db import DB_PATH
from editor import edit_recording
from analyzer import analyze_recording
from thumbnail import generate_thumbnail

logger = logging.getLogger(__name__)

GPU_SERVICE_URL = os.environ.get("GPU_SERVICE_URL", "http://10.190.0.203:8877")
RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), "..", "recordings")
POLL_INTERVAL = 60  # seconds


async def poll_transcriptions(broadcast_fn=None):
    """Background loop: poll GPU service for completed transcriptions."""
    while True:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM recordings WHERE transcribed = 1 AND gpu_job_id IS NOT NULL"
                ) as cur:
                    pending = await cur.fetchall()

            if pending:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    for rec in pending:
                        await _check_job(client, rec, broadcast_fn)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Transcription poll error: {e}")

        await asyncio.sleep(POLL_INTERVAL)


async def _check_job(client: httpx.AsyncClient, rec, broadcast_fn):
    job_id = rec["gpu_job_id"]
    try:
        resp = await client.get(f"{GPU_SERVICE_URL}/jobs/{job_id}")
    except Exception as e:
        logger.warning(f"Cannot reach GPU service for job {job_id}: {e}")
        return

    if resp.status_code != 200:
        return

    job = resp.json()
    if job["status"] == "done":
        await _fetch_srt(client, rec["id"], job_id, rec["filename"])
        if broadcast_fn:
            try:
                await broadcast_fn({"type": "transcribed", "recording_id": rec["id"]})
            except Exception:
                pass
    elif job["status"] == "error":
        logger.error(f"GPU transcription error for {rec['filename']}: {job.get('error')}")
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE recordings SET transcribed = -1 WHERE id = ?", (rec["id"],)
            )
            await db.commit()


async def _fetch_srt(client: httpx.AsyncClient, recording_id: int, job_id: str, filename: str):
    srt_filename = os.path.splitext(filename)[0] + ".srt"
    local_srt = os.path.join(RECORDINGS_DIR, srt_filename)
    try:
        resp = await client.get(
            f"{GPU_SERVICE_URL}/jobs/{job_id}/srt",
            timeout=30.0,
        )
        if resp.status_code == 200:
            with open(local_srt, "wb") as f:
                f.write(resp.content)
            logger.info(f"SRT fetched: {srt_filename}")
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE recordings SET transcribed = 2 WHERE id = ?", (recording_id,)
                )
                await db.commit()
            # Trigger smart editing in background
            mp4_path = os.path.join(RECORDINGS_DIR, filename)
            asyncio.create_task(_run_editor(recording_id, mp4_path, local_srt))
        else:
            logger.error(f"SRT download failed for {job_id}: {resp.status_code}")
    except Exception as e:
        logger.error(f"SRT fetch error for {job_id}: {e}")


async def _run_editor(recording_id: int, mp4_path: str, srt_path: str):
    """Run editor and update DB with result."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE recordings SET clipped = 1 WHERE id = ?", (recording_id,)
        )
        await db.commit()
    try:
        # Fetch room name and recording date for organised output path
        room_name = "unknown"
        date_str = ""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT r.start_time, rm.name as room_name "
                    "FROM recordings r JOIN rooms rm ON r.room_id = rm.id WHERE r.id = ?",
                    (recording_id,)
                ) as cur:
                    info = await cur.fetchone()
            if info:
                room_name = info["room_name"] or "unknown"
                date_str = (info["start_time"] or "")[:10].replace("-", "")
        except Exception as e:
            logger.warning(f"Could not fetch room info for recording {recording_id}: {e}")

        clip_path = await edit_recording(mp4_path, srt_path, room_name=room_name, record_date=date_str)
        if clip_path:
            clip_filename = os.path.relpath(clip_path, RECORDINGS_DIR)
            thumb = await generate_thumbnail(clip_path)
            thumb_basename = os.path.relpath(thumb, RECORDINGS_DIR) if thumb else None
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE recordings SET clipped = 2, clip_filename = ?, thumbnail = ? WHERE id = ?",
                    (clip_filename, thumb_basename, recording_id),
                )
                # Get room_id for analysis
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT room_id, filename FROM recordings WHERE id = ?", (recording_id,)
                ) as cur:
                    rec = await cur.fetchone()
                await db.commit()
            logger.info(f"Clip saved: {clip_filename}")
            if rec:
                asyncio.create_task(
                    analyze_recording(recording_id, rec["filename"], rec["room_id"])
                )
        else:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE recordings SET clipped = -1 WHERE id = ?", (recording_id,)
                )
                await db.commit()
    except Exception as e:
        logger.error(f"Editor failed for recording {recording_id}: {e}")
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE recordings SET clipped = -1 WHERE id = ?", (recording_id,)
            )
            await db.commit()
