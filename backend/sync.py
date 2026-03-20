import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

GPU_SERVICE_URL = os.environ.get("GPU_SERVICE_URL", "http://10.190.0.203:8877")


async def sync_file(local_path: str, room_id: int) -> Optional[str]:
    """Upload MP4 to GPU transcription service. Returns job_id on success, None on failure."""
    filename = os.path.basename(local_path)
    url = f"{GPU_SERVICE_URL}/jobs"
    logger.info(f"Uploading {filename} to GPU service...")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
            with open(local_path, "rb") as f:
                resp = await client.post(
                    url,
                    data={"room_id": str(room_id)},
                    files={"file": (filename, f, "video/mp4")},
                )
        if resp.status_code == 201:
            job_id = resp.json()["job_id"]
            logger.info(f"Uploaded {filename}, job_id={job_id}")
            return job_id
        else:
            logger.error(f"Upload failed for {filename}: {resp.status_code} {resp.text}")
            return None
    except Exception as e:
        logger.error(f"Upload error for {filename}: {e}")
        return None
