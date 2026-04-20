import asyncio
import logging
import os
from typing import Optional

import aiohttp
import httpx

logger = logging.getLogger(__name__)

GPU_SERVICE_URL = os.environ.get("GPU_SERVICE_URL", "http://10.190.0.203:8877")


async def sync_file(local_path: str, room_id: int) -> Optional[str]:
    """Upload MP4 to GPU transcription service. Returns job_id on success, None on failure.
    Retries up to 3 times with exponential backoff on transient errors."""
    filename = os.path.basename(local_path)
    url = f"{GPU_SERVICE_URL}/jobs"

    for attempt in range(1, 4):
        try:
            logger.info(f"Uploading {filename} to GPU service (attempt {attempt}/3)...")
            with open(local_path, "rb") as f:
                file_data = f.read()
            form = aiohttp.FormData()
            form.add_field("room_id", str(room_id))
            form.add_field("file", file_data, filename=filename, content_type="video/mp4")
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=form,
                                        timeout=aiohttp.ClientTimeout(total=300)) as resp:
                    _up_status = resp.status
                    _up_body = await resp.json() if _up_status in (200, 201) else None
                    _up_text = await resp.text() if _up_body is None else ""
            if _up_status == 201:
                job_id = _up_body["job_id"]
                logger.info(f"Uploaded {filename}, job_id={job_id}")
                return job_id
            elif _up_status >= 500 and attempt < 3:
                logger.warning(f"Upload {filename}: server error {_up_status}, retrying...")
            else:
                logger.error(f"Upload failed for {filename}: {_up_status} {_up_text[:200]}")
                return None
        except Exception as e:
            if attempt < 3:
                logger.warning(f"Upload {filename}: transient error ({e}), retrying...")
            else:
                logger.error(f"Upload error for {filename} after 3 attempts: {e}")
                return None

        await asyncio.sleep(2 ** attempt)  # 2s, 4s backoff

    return None
