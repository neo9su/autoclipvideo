"""
GPU access locks — two independent semaphores for clip and enhance workloads.

Clip jobs use NVENC (dedicated hardware encoder, no VRAM cost) while enhance
jobs use CUDA/VRAM (Real-ESRGAN).  They do not contest the same resource, so
they get separate locks:

  gpu_slot("clip:…")    — serialises clip jobs (avoids hammering NVENC)
  enhance_slot("…")     — serialises enhance/CUDA jobs (avoids VRAM OOM)

Neither blocks the other.  The GPU service enforces its own concurrency
limits internally (_clip_sem=2, _gpu_sem=1).

Usage:
    from gpu_lock import gpu_slot, enhance_slot, gpu_slot_status

    async with gpu_slot("clip:filename.mp4"):
        # submit clip job to GPU, poll, download ...

    async with enhance_slot("enhance:job_id"):
        # submit enhance job to GPU, poll, download ...
"""
import asyncio
import logging
import time

logger = logging.getLogger(__name__)

# ── Clip slot (NVENC) ─────────────────────────────────────────────────────────
_clip_sem: asyncio.Semaphore | None = None
_clip_holder: str = ""
_clip_acquired_at: float = 0.0

# ── Enhance slot (CUDA/VRAM) ──────────────────────────────────────────────────
_enhance_sem: asyncio.Semaphore | None = None
_enhance_holder: str = ""
_enhance_acquired_at: float = 0.0


def _get_clip_sem() -> asyncio.Semaphore:
    global _clip_sem
    if _clip_sem is None:
        _clip_sem = asyncio.Semaphore(1)
    return _clip_sem


def _get_enhance_sem() -> asyncio.Semaphore:
    global _enhance_sem
    if _enhance_sem is None:
        _enhance_sem = asyncio.Semaphore(1)
    return _enhance_sem


class _Slot:
    def __init__(self, desc: str, get_sem, holder_ref: list, acquired_ref: list):
        self._desc = desc
        self._get_sem = get_sem
        self._holder = holder_ref    # [str]
        self._acquired = acquired_ref  # [float]

    async def __aenter__(self):
        s = self._get_sem()
        if s.locked():
            logger.info(f"GPU slot: '{self._desc}' waiting (currently held by '{self._holder[0]}')")
        await s.acquire()
        self._holder[0] = self._desc
        self._acquired[0] = time.time()
        logger.debug(f"GPU slot acquired: {self._desc}")
        return self

    async def __aexit__(self, *_):
        prev = self._holder[0]
        self._holder[0] = ""
        self._acquired[0] = 0.0
        self._get_sem().release()
        logger.debug(f"GPU slot released: {prev}")


_clip_holder_ref = [""]
_clip_acquired_ref = [0.0]
_enhance_holder_ref = [""]
_enhance_acquired_ref = [0.0]


def gpu_slot(desc: str = "") -> _Slot:
    """Async context manager: serialise NVENC clip jobs (does NOT block enhance)."""
    return _Slot(desc, _get_clip_sem, _clip_holder_ref, _clip_acquired_ref)


def enhance_slot(desc: str = "") -> _Slot:
    """Async context manager: serialise CUDA enhance jobs (does NOT block clips)."""
    return _Slot(desc, _get_enhance_sem, _enhance_holder_ref, _enhance_acquired_ref)


def gpu_slot_status() -> dict:
    """Return current lock state for health / monitoring endpoints."""
    clip_locked = _get_clip_sem().locked()
    enh_locked  = _get_enhance_sem().locked()
    return {
        "locked": clip_locked or enh_locked,
        "holder": _clip_holder_ref[0] or _enhance_holder_ref[0],
        "held_seconds": round(time.time() - _clip_acquired_ref[0], 1) if clip_locked and _clip_acquired_ref[0] else
                        round(time.time() - _enhance_acquired_ref[0], 1) if enh_locked and _enhance_acquired_ref[0] else 0,
        "clip_slot": {
            "locked": clip_locked,
            "holder": _clip_holder_ref[0],
            "held_seconds": round(time.time() - _clip_acquired_ref[0], 1) if clip_locked and _clip_acquired_ref[0] else 0,
        },
        "enhance_slot": {
            "locked": enh_locked,
            "holder": _enhance_holder_ref[0],
            "held_seconds": round(time.time() - _enhance_acquired_ref[0], 1) if enh_locked and _enhance_acquired_ref[0] else 0,
        },
    }
