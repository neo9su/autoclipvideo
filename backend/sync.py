import asyncio
import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

import aiohttp
import httpx

from gpu_execution import TransferStats, require_remote_gpu

logger = logging.getLogger(__name__)

GPU_SERVICE_URL = os.environ.get("GPU_SERVICE_URL", "http://10.190.0.203:8877")


async def sync_file(local_path: str, room_id: int, stats: Optional[TransferStats] = None) -> Optional[str]:
    """Upload one MP4 once, with a stable idempotency key for safe retries."""
    path = Path(local_path)
    if not path.is_file():
        raise FileNotFoundError(local_path)
    record = require_remote_gpu("media upload")
    file_size = path.stat().st_size
    key = hashlib.sha256(f"{room_id}:{path.name}:{file_size}:{path.stat().st_mtime_ns}".encode()).hexdigest()
    transfer = stats or TransferStats("upload", record.node)
    headers = {"X-Idempotency-Key": key, "X-Execution-Node": record.node}
    transfer.input_bytes = file_size
    transfer.idempotency_key = key
    url = f"{GPU_SERVICE_URL.rstrip('/')}/jobs"

    for attempt in range(1, 4):
        transfer.upload_attempts = attempt
        try:
            logger.info("Uploading %s to GPU service (attempt %s/3, bytes=%s)", path.name, attempt, file_size)
            form = aiohttp.FormData()
            form.add_field("room_id", str(room_id))
            with path.open("rb") as media_file:
                form.add_field("file", media_file, filename=path.name, content_type="video/mp4")
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        url,
                        data=form,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=300),
                    ) as resp:
                        status = resp.status
                        body = await resp.json() if status in (200, 201) else None
                        text = "" if body is not None else await resp.text()
            if status in (200, 201) and body and body.get("job_id"):
                logger.info("GPU upload accepted %s as job %s", path.name, body["job_id"])
                return body["job_id"]
            if status < 500:
                logger.error("Upload failed for %s: %s %s", path.name, status, text[:200])
                return None
            logger.warning("Upload %s: server error %s, retrying", path.name, status)
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            logger.warning("Upload %s transient error (%s), retrying", path.name, type(exc).__name__)
        await asyncio.sleep(2 ** attempt)
    logger.error("Upload error for %s after 3 attempts", path.name)
    return None
