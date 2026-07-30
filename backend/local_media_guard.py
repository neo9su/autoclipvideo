"""Local media-processing guardrails for small-memory macOS hosts.

Heavy ffmpeg encodes can make WindowServer miss watchdog check-ins on 8GB Macs
when several jobs run at once. Keep local media work serialized and provide a
cheap memory-pressure gate before starting a new process.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import threading
from contextlib import asynccontextmanager, contextmanager

logger = logging.getLogger(__name__)

_MAX_LOCAL_MEDIA_JOBS = max(1, int(os.environ.get("LOCAL_MEDIA_MAX_CONCURRENT", "1")))
_LOCAL_MEDIA_SEM = threading.BoundedSemaphore(_MAX_LOCAL_MEDIA_JOBS)
_MEMORYPRESSURE_MIN_FREE_PCT = int(os.environ.get("LOCAL_MEDIA_MIN_FREE_PCT", "12"))
_MEMORYPRESSURE_MAX_WAIT_S = float(os.environ.get("LOCAL_MEDIA_MEMORY_WAIT_SECONDS", "180"))


def _memory_pressure_ok_sync() -> bool:
    """Return True when macOS reports enough free memory to start ffmpeg."""
    if os.uname().sysname != "Darwin":
        return True
    try:
        result = subprocess.run(
            ["memory_pressure"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as e:
        logger.debug("memory_pressure check skipped: %s", e)
        return True

    text = (result.stdout or "") + (result.stderr or "")
    for line in text.splitlines():
        line = line.strip()
        try:
            if line.startswith("The system has ") and "% free" in line:
                pct = int(line.split("The system has ", 1)[1].split("% free", 1)[0])
                return pct >= _MEMORYPRESSURE_MIN_FREE_PCT
            if line.startswith("System-wide memory free percentage:"):
                pct = int(line.rsplit(":", 1)[1].strip().rstrip("%"))
                return pct >= _MEMORYPRESSURE_MIN_FREE_PCT
        except Exception:
            return True
    # If the format changes, do not hard-fail production work.
    return True


async def wait_for_memory_headroom(desc: str = "local media job") -> None:
    """Wait briefly for memory headroom; continue with a warning if still tight."""
    deadline = asyncio.get_running_loop().time() + _MEMORYPRESSURE_MAX_WAIT_S
    warned = False
    while not await asyncio.to_thread(_memory_pressure_ok_sync):
        if not warned:
            logger.warning(
                "%s waiting for memory headroom before local ffmpeg (min_free=%s%%)",
                desc,
                _MEMORYPRESSURE_MIN_FREE_PCT,
            )
            warned = True
        if asyncio.get_running_loop().time() >= deadline:
            logger.warning("%s starting despite sustained memory pressure", desc)
            return
        await asyncio.sleep(10)


@asynccontextmanager
async def local_media_slot(desc: str = "local media job"):
    """Serialize local ffmpeg/media jobs and gate them on memory pressure."""
    acquired = _LOCAL_MEDIA_SEM.acquire(blocking=False)
    if not acquired:
        logger.info("%s waiting for local media slot", desc)
        await asyncio.to_thread(_LOCAL_MEDIA_SEM.acquire)
        acquired = True
    try:
        await wait_for_memory_headroom(desc)
        yield
    finally:
        if acquired:
            _LOCAL_MEDIA_SEM.release()


@contextmanager
def local_media_slot_sync(desc: str = "local media job"):
    """Synchronous variant for rare blocking ffmpeg call sites."""
    acquired = _LOCAL_MEDIA_SEM.acquire(blocking=False)
    if not acquired:
        logger.info("%s waiting for local media slot", desc)
        _LOCAL_MEDIA_SEM.acquire()
        acquired = True
    try:
        if not _memory_pressure_ok_sync():
            logger.warning("%s starting under memory pressure", desc)
        yield
    finally:
        if acquired:
            _LOCAL_MEDIA_SEM.release()
