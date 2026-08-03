"""Idempotent control-plane transfer to the remote GPU service."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import aiohttp
import aiosqlite

from db import DB_PATH
from gpu_execution import media_fingerprint, require_remote_gpu

logger = logging.getLogger(__name__)
GPU_SERVICE_URL = os.environ.get("GPU_SERVICE_URL", "http://10.190.0.203:8877").rstrip("/")
_MAX_UPLOAD_ATTEMPTS = 2


async def _existing_job(file_key: str) -> Optional[str]:
    """Return a previously submitted job for this exact artifact, if known."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT gpu_job_id FROM gpu_transfers WHERE idempotency_key = ? LIMIT 1",
                (file_key,),
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else None
    except Exception:
        return None


async def sync_file(local_path: str, room_id: int) -> Optional[str]:
    """Upload one artifact once, with bounded retry and an idempotency key."""
    require_remote_gpu("media upload")
    if not os.path.isfile(local_path):
        raise FileNotFoundError(local_path)
    filename = os.path.basename(local_path)
    file_key = media_fingerprint(local_path)
    known_job = await _existing_job(file_key)
    if known_job:
        logger.info("Skipping duplicate GPU upload for %s", filename)
        return known_job

    url = f"{GPU_SERVICE_URL}/jobs"
    file_size = os.path.getsize(local_path)
    for attempt in range(1, _MAX_UPLOAD_ATTEMPTS + 1):
        try:
            with open(local_path, "rb") as source:
                form = aiohttp.FormData()
                form.add_field("room_id", str(room_id))
                form.add_field("idempotency_key", file_key)
                form.add_field("execution_node", "remote-gpu")
                form.add_field("file", source, filename=filename, content_type="video/mp4")
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        url, data=form,
                        headers={"X-Idempotency-Key": file_key},
                        timeout=aiohttp.ClientTimeout(total=300),
                    ) as response:
                        body = await response.json() if response.status in (200, 201) else None
                        text = "" if body is not None else (await response.text())[:200]
            if response.status == 201 and body and body.get("job_id"):
                job_id = body["job_id"]
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        """INSERT OR REPLACE INTO gpu_transfers
                           (idempotency_key, filename, room_id, input_bytes, gpu_job_id,
                            execution_node, uploaded_bytes)
                           VALUES (?, ?, ?, ?, ?, 'remote-gpu', ?)""",
                        (file_key, filename, room_id, file_size, job_id, file_size),
                    )
                    await db.commit()
                logger.info("GPU upload complete: file=%s bytes=%d node=remote-gpu", filename, file_size)
                return job_id
            if response.status >= 500 and attempt < _MAX_UPLOAD_ATTEMPTS:
                await asyncio.sleep(2 ** attempt)
                continue
            logger.error("GPU upload rejected: file=%s status=%s detail=%s", filename, response.status, text)
            return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as error:
            if attempt == _MAX_UPLOAD_ATTEMPTS:
                logger.error("GPU upload unavailable: file=%s attempts=%d error=%s", filename, attempt, error)
                return None
            await asyncio.sleep(2 ** attempt)
    return None
