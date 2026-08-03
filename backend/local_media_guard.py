"""Compatibility guard for the control plane.

The control-plane host is not an execution node. This module is retained so
legacy imports fail closed instead of reviving the former local ffmpeg path.
"""
from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager

from gpu_execution import reject_local_media


@asynccontextmanager
async def local_media_slot(desc: str = "local media job"):
    """Fail closed when legacy code asks for a local media slot."""
    reject_local_media(desc)
    yield


@contextmanager
def local_media_slot_sync(desc: str = "local media job"):
    """Fail closed for synchronous legacy media call sites."""
    reject_local_media(desc)
    yield
