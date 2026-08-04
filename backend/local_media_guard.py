"""Fail-closed guard for deprecated local media-processing call sites."""

from gpu_execution import reject_local_media


async def wait_for_memory_headroom(desc: str = "media job") -> None:
    """Fail instead of waiting for a local media execution slot."""
    reject_local_media(desc)


class _RejectedMediaSlot:
    async def __aenter__(self):
        reject_local_media("local media slot")

    async def __aexit__(self, exc_type, exc, tb):
        return False


def local_media_slot(desc: str = "media job"):
    """Compatibility shim that makes every local media call fail closed."""
    del desc
    return _RejectedMediaSlot()


def local_media_slot_sync(desc: str = "media job"):
    """Compatibility shim for synchronous callers; local media is disabled."""
    del desc
    reject_local_media("local media slot")
