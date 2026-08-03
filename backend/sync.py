import asyncio
import hashlib
import logging
import os
from dataclasses import dataclass
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

GPU_SERVICE_URL = os.environ.get("GPU_SERVICE_URL", "http://10.190.0.203:8877").rstrip("/")
GPU_EXECUTION_NODE = os.environ.get("GPU_EXECUTION_NODE", "remote-gpu")
_UPLOAD_CONCURRENCY = max(1, int(os.environ.get("GPU_UPLOAD_CONCURRENCY", "2")))
_UPLOAD_SEMAPHORE = asyncio.Semaphore(_UPLOAD_CONCURRENCY)
_IN_FLIGHT: dict[str, asyncio.Task[Optional[str]]] = {}
_IN_FLIGHT_LOCK = asyncio.Lock()


@dataclass(frozen=True)
class TransferMetrics:
    """Control-plane transfer accounting for one upload request."""

    transfer_id: str
    execution_node: str
    input_bytes: int
    upload_attempts: int


_LAST_TRANSFER: dict[str, TransferMetrics] = {}


def transfer_metrics(transfer_id: str) -> Optional[TransferMetrics]:
    """Return the last recorded metrics for a transfer, if available."""
    return _LAST_TRANSFER.get(transfer_id)


def _transfer_id(local_path: str, room_id: int) -> str:
    stat = os.stat(local_path)
    identity = f"{room_id}:{os.path.abspath(local_path)}:{stat.st_size}:{stat.st_mtime_ns}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


async def sync_file(local_path: str, room_id: int) -> Optional[str]:
    """Upload a media artifact to the remote GPU without local processing.

    The content identity and bounded concurrency prevent multiple pollers from
    moving the same large artifact at the same time.
    """
    transfer_id = _transfer_id(local_path, room_id)
    async with _IN_FLIGHT_LOCK:
        task = _IN_FLIGHT.get(transfer_id)
        if task is None:
            task = asyncio.create_task(_sync_file_once(local_path, room_id, transfer_id))
            _IN_FLIGHT[transfer_id] = task
    try:
        return await task
    finally:
        if task.done():
            async with _IN_FLIGHT_LOCK:
                if _IN_FLIGHT.get(transfer_id) is task:
                    _IN_FLIGHT.pop(transfer_id, None)


async def _sync_file_once(local_path: str, room_id: int, transfer_id: str) -> Optional[str]:
    filename = os.path.basename(local_path)
    url = f"{GPU_SERVICE_URL}/jobs"
    input_bytes = os.path.getsize(local_path)
    attempts = 0

    async with _UPLOAD_SEMAPHORE:
        for attempt in range(1, 4):
            attempts = attempt
            try:
                logger.info(
                    "Uploading %s (attempt %d/3, bytes=%d, node=%s)",
                    filename, attempt, input_bytes, GPU_EXECUTION_NODE,
                )
                form = aiohttp.FormData()
                form.add_field("room_id", str(room_id))
                form.add_field("execution_node", GPU_EXECUTION_NODE)
                with open(local_path, "rb") as media_file:
                    form.add_field("file", media_file, filename=filename, content_type="video/mp4")
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            url,
                            data=form,
                            headers={
                                "X-Idempotency-Key": transfer_id,
                                "X-Execution-Node": GPU_EXECUTION_NODE,
                            },
                            timeout=aiohttp.ClientTimeout(total=300),
                        ) as response:
                            status = response.status
                            body = await response.json() if status in (200, 201) else None
                            text = await response.text() if body is None else ""
                if status in (200, 201):
                    job_id = body["job_id"]
                    _LAST_TRANSFER[transfer_id] = TransferMetrics(
                        transfer_id, GPU_EXECUTION_NODE, input_bytes, attempts,
                    )
                    logger.info(
                        "Uploaded %s, job_id=%s, bytes=%d, attempts=%d",
                        filename, job_id, input_bytes, attempts,
                    )
                    return job_id
                if status >= 500 and attempt < 3:
                    logger.warning("Upload %s: server error %s, retrying", filename, status)
                else:
                    logger.error("Upload failed for %s: %s %s", filename, status, text[:200])
                    return None
            except (OSError, aiohttp.ClientError) as exc:
                if attempt < 3:
                    logger.warning("Upload %s transient error (%s), retrying", filename, exc)
                else:
                    logger.error("Upload error for %s after 3 attempts: %s", filename, exc)
                    return None
            await asyncio.sleep(2 ** attempt)
    return None
