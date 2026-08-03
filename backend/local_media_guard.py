"""Compatibility boundary for disabled local media processing."""
from __future__ import annotations

from gpu_execution import reject_local_media


class _DisabledLocalMediaSlot:
    async def __aenter__(self):
        reject_local_media("local media slot")

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def local_media_slot(desc: str = "local media job"):
    """Retain the old import surface while making local work unreachable."""
    return _DisabledLocalMediaSlot()


def local_media_slot_sync(desc: str = "local media job"):
    reject_local_media(desc)
