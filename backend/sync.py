"""Idempotent control-plane uploads to the remote GPU service.

This module transfers source artifacts only.  It never processes media locally.
"""
import asyncio
import hashlib
import logging
import os
from dataclasses import dataclass
from typing import Optional

import aiohttp

from gpu_execution import require_remote_gpu

logger = logging.getLogger(__name__)
GPU_SERVICE_URL = os.environ.get("GPU_SERVICE_URL", "http://10.190.0.203:8877").rstrip("/")
_UPLOAD_RETRIES = 3
_UPLOAD_TIMEOUT = aiohttp.ClientTimeout(total=1800)  # 30 minutes for large files


@dataclass(frozen=True)
class TransferStats:
    job_id: str
    node: str
    input_bytes: int
    upload_attempts: int


_completed_uploads: dict[str, TransferStats] = {}
_upload_locks: dict[str, asyncio.Lock] = {}
_upload_locks_guard = asyncio.Lock()
_last_transfer_stats: Optional[TransferStats] = None


def last_transfer_stats() -> Optional[TransferStats]:
    """Return the most recent transfer counters for health/status reporting."""
    return _last_transfer_stats


async def invalidate_upload(local_path: str, room_id: int) -> None:
    """Forget a cached job after the remote service lost it during restart."""
    try:
        fingerprint, _ = await asyncio.to_thread(_file_fingerprint, local_path)
    except (OSError, ValueError):
        return
    _completed_uploads.pop(f"{room_id}:{fingerprint}", None)


def _file_fingerprint(path: str) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


async def _validate_mp4_source(local_path: str) -> tuple[bool, str]:
    """Reject empty or unreadable MP4s before they reach the GPU queue."""
    try:
        if os.path.getsize(local_path) <= 0:
            return False, "source media is empty"
        process = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", local_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
        if process.returncode != 0:
            detail = stderr.decode(errors="replace").strip()[-160:]
            return False, f"invalid mp4: {detail or 'ffprobe failed'}"
        try:
            if float(stdout.decode().strip()) <= 0:
                return False, "invalid mp4: duration is 0"
        except ValueError:
            return False, "invalid mp4: duration is unavailable"
    except asyncio.TimeoutError:
        try:
            process.kill()
        except Exception:
            pass
        return False, "invalid mp4: ffprobe timeout"
    except (OSError, ValueError) as exc:
        return False, f"invalid mp4: {type(exc).__name__}"
    return True, ""


async def sync_file(local_path: str, room_id: int) -> Optional[str]:
    """Upload one source file once and return its remote transcription job id.

    A content fingerprint is used as the idempotency key.  Repeated callers in
    this process return the existing job id instead of rereading/uploading the
    same large file.  GPU unavailability is reported as failure to the caller;
    callers keep the job queued and must not invoke a local fallback.
    """
    global _last_transfer_stats
    if not os.path.isfile(local_path) or os.path.getsize(local_path) <= 0:
        logger.warning("Upload source does not exist: %s", os.path.basename(local_path))
        return None
    require_remote_gpu("source upload")

    valid, reason = await _validate_mp4_source(local_path)
    if not valid:
        logger.warning("Upload source rejected for %s: %s", os.path.basename(local_path), reason)
        return None

    fingerprint, input_bytes = await asyncio.to_thread(_file_fingerprint, local_path)
    if input_bytes == 0:
        logger.warning("Upload source is empty: %s", os.path.basename(local_path))
        return None
    cache_key = f"{room_id}:{fingerprint}"
    async with _upload_locks_guard:
        upload_lock = _upload_locks.setdefault(cache_key, asyncio.Lock())

    async with upload_lock:
        cached = _completed_uploads.get(cache_key)
        if cached:
            _last_transfer_stats = cached
            logger.info("Reusing remote upload job=%s bytes=%d node=%s", cached.job_id, cached.input_bytes, cached.node)
            return cached.job_id

        filename = os.path.basename(local_path)
        url = f"{GPU_SERVICE_URL}/jobs"
        for attempt in range(1, _UPLOAD_RETRIES + 1):
            try:
                def _read_source() -> bytes:
                    with open(local_path, "rb") as source:
                        return source.read()
                file_data = await asyncio.to_thread(_read_source)
                form = aiohttp.FormData()
                form.add_field("room_id", str(room_id))
                form.add_field("file", file_data, filename=filename, content_type="video/mp4")
                headers = {"X-Idempotency-Key": cache_key}
                async with aiohttp.ClientSession(timeout=_UPLOAD_TIMEOUT) as session:
                    async with session.post(url, data=form, headers=headers) as response:
                        body = await response.json() if response.status in (200, 201) else None
                        text = "" if body is not None else await response.text()
                if response.status == 201 and body and body.get("job_id"):
                    stats = TransferStats(body["job_id"], os.environ.get("GPU_EXECUTION_NODE", "remote-gpu"), input_bytes, attempt)
                    _completed_uploads[cache_key] = stats
                    _last_transfer_stats = stats
                    logger.info("Uploaded %s bytes=%d attempts=%d node=%s job=%s", filename, input_bytes, attempt, stats.node, stats.job_id)
                    return stats.job_id
                if response.status < 500:
                    logger.error("Upload rejected for %s: status=%s detail=%s", filename, response.status, text[:200])
                    return None
                logger.warning("Upload server error for %s: status=%s attempt=%d/%d", filename, response.status, attempt, _UPLOAD_RETRIES)
            except Exception as exc:
                logger.warning("Upload error for %s attempt=%d/%d: %s", filename, attempt, _UPLOAD_RETRIES, type(exc).__name__)
            if attempt < _UPLOAD_RETRIES:
                await asyncio.sleep(2 ** attempt)
        return None
