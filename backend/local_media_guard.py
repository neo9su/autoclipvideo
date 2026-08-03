"""Compatibility guard for the control-plane process.

The Mac is not a media worker. These APIs remain import-compatible for older
callers, but every attempted local media slot fails immediately instead of
serialising or starting a hidden ffmpeg fallback.
"""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager


class LocalMediaDisabledError(RuntimeError):
    """Raised when a control-plane path attempts local media processing."""


@asynccontextmanager
async def local_media_slot(desc: str = "local media job"):
    """Reject local media work; callers must submit a remote GPU job."""
    raise LocalMediaDisabledError(f"local media execution is disabled: {desc}")
    yield


@contextmanager
def local_media_slot_sync(desc: str = "local media job"):
    """Synchronous compatibility API that rejects local media work."""
    raise LocalMediaDisabledError(f"local media execution is disabled: {desc}")
    yield
