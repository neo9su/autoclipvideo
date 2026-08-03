"""Remote GPU transfer client with bounded, content-addressed uploads."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from typing import Optional

import aiohttp

from gpu_execution import require_remote_gpu

logger = logging.getLogger(__name__)
GPU_SERVICE_URL = os.environ.get("GPU_SERVICE_URL", "http://10.190.0.203:8877").rstrip("/")
_TRANSFER_SEMAPHORE = asyncio.Semaphore(1)
_TRANSFER_CACHE: dict[tuple[str, int, int], str] = {}
_TRANSFER_BYTES_UPLOADED = 0


def transfer_stats() -> dict:
    return {"uploads": len(_TRANSFER_CACHE), "bytes_uploaded": _TRANSFER_BYTES_UPLOADED, "in_flight_limit": 1}


def _transfer_key(local_path: str) -> tuple[str, int, int]:
    stat = os.stat(local_path)
    return (os.path.abspath(local_path), stat.st_size, stat.st_mtime_ns)


async def sync_file(local_path: str, room_id: int) -> Optional[str]:
    """Upload one source once; never process or retry-copy it locally."""
    global _TRANSFER_BYTES_UPLOADED
    require_remote_gpu("source upload")
    if not local_path or not os.path.isfile(local_path):
        raise FileNotFoundError(local_path)
    key = _transfer_key(local_path)
    if key in _TRANSFER_CACHE:
        logger.info("GPU transfer reuse: node=remote-gpu file=%s", os.path.basename(local_path))
        return _TRANSFER_CACHE[key]
    filename = os.path.basename(local_path)
    digest = hashlib.sha256()
    async with _TRANSFER_SEMAPHORE:
        if key in _TRANSFER_CACHE:
            return _TRANSFER_CACHE[key]
        with open(local_path, "rb") as source:
            file_data = source.read()
        digest.update(file_data)
        form = aiohttp.FormData()
        form.add_field("room_id", str(room_id))
        form.add_field("sha256", digest.hexdigest())
        form.add_field("file", file_data, filename=filename, content_type="video/mp4")
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{GPU_SERVICE_URL}/jobs", data=form,
                                    timeout=aiohttp.ClientTimeout(total=300)) as response:
                if response.status not in (200, 201):
                    body = (await response.text())[:200]
                    raise RuntimeError(f"GPU upload failed ({response.status}): {body}")
                payload = await response.json()
        job_id = payload.get("job_id")
        if not job_id:
            raise RuntimeError("GPU upload response did not contain job_id")
        _TRANSFER_CACHE[key] = str(job_id)
        _TRANSFER_BYTES_UPLOADED += len(file_data)
        logger.info("GPU transfer complete: node=remote-gpu bytes=%d job_id=%s", len(file_data), job_id)
        return str(job_id)
