"""Remote-only upload coordinator with bounded, idempotent transfers."""
import asyncio
import logging
import os
from typing import Optional

import aiohttp

from gpu_execution import require_remote_gpu

logger = logging.getLogger(__name__)

GPU_SERVICE_URL = os.environ.get("GPU_SERVICE_URL", "http://10.190.0.203:8877").rstrip("/")
_UPLOAD_SEMAPHORE = asyncio.Semaphore(max(1, int(os.environ.get("GPU_UPLOAD_CONCURRENCY", "1"))))
_MAX_UPLOAD_ATTEMPTS = max(1, int(os.environ.get("GPU_UPLOAD_ATTEMPTS", "3")))


async def sync_file(local_path: str, room_id: int) -> Optional[str]:
    """Upload one source exactly once per call and return its remote job id.

    The remote service receives a stable idempotency key. Network retries reuse
    the same key and never trigger local processing or a second in-memory copy.
    """
    require_remote_gpu("media upload")
    if not local_path or not os.path.isfile(local_path):
        raise FileNotFoundError(local_path)
    filename = os.path.basename(local_path)
    size_bytes = os.path.getsize(local_path)
    idempotency_key = f"room:{room_id}:file:{filename}:size:{size_bytes}"
    url = f"{GPU_SERVICE_URL}/jobs"

    async with _UPLOAD_SEMAPHORE:
        for attempt in range(1, _MAX_UPLOAD_ATTEMPTS + 1):
            try:
                logger.info("Uploading %s bytes=%d attempt=%d/%d node=remote-gpu", filename, size_bytes, attempt, _MAX_UPLOAD_ATTEMPTS)
                form = aiohttp.FormData()
                form.add_field("room_id", str(room_id))
                with open(local_path, "rb") as media_file:
                    form.add_field("file", media_file, filename=filename, content_type="video/mp4")
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            url,
                            data=form,
                            headers={"Idempotency-Key": idempotency_key},
                            timeout=aiohttp.ClientTimeout(total=300),
                        ) as response:
                            if response.status == 201:
                                body = await response.json()
                                job_id = body.get("job_id")
                                if job_id:
                                    logger.info("Uploaded %s bytes=%d job=%s node=remote-gpu", filename, size_bytes, job_id)
                                    return job_id
                            response_text = await response.text()
                            if response.status < 500 or attempt == _MAX_UPLOAD_ATTEMPTS:
                                logger.error("Upload failed for %s status=%d body=%s", filename, response.status, response_text[:200])
                                return None
            except (aiohttp.ClientError, asyncio.TimeoutError) as error:
                if attempt == _MAX_UPLOAD_ATTEMPTS:
                    logger.error("Upload failed for %s after %d attempts: %s", filename, attempt, error)
                    return None
                logger.warning("Upload transient failure for %s attempt=%d: %s", filename, attempt, error)
            await asyncio.sleep(2 ** attempt)
    return None
