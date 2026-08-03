"""Fail-closed compatibility boundary for the retired local media pipeline.

The Mac process is a control plane. Legacy imports remain available so callers
fail explicitly instead of silently re-enabling local ffmpeg work.
"""
from contextlib import asynccontextmanager, contextmanager

from gpu_execution import reject_local_media


@asynccontextmanager
async def local_media_slot(desc: str = "local media job"):
    """Fail closed for legacy async callers; no local slot exists anymore."""
    reject_local_media(desc)
    yield


@contextmanager
def local_media_slot_sync(desc: str = "local media job"):
    """Fail closed for legacy synchronous callers."""
    reject_local_media(desc)
    yield
