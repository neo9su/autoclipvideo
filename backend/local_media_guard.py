"""Compatibility guard for the retired local media pipeline."""
from contextlib import asynccontextmanager, contextmanager


@asynccontextmanager
async def local_media_slot(desc: str = "local media job"):
    from gpu_execution import reject_local_media
    reject_local_media(desc)
    yield


@contextmanager
def local_media_slot_sync(desc: str = "local media job"):
    from gpu_execution import reject_local_media
    reject_local_media(desc)
    yield


async def wait_for_memory_headroom(desc: str = "local media job") -> None:
    from gpu_execution import reject_local_media
    reject_local_media(desc)
