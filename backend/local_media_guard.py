"""Fail-closed compatibility guard for the retired local media pipeline."""
from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager

from gpu_execution import RemoteGpuRequiredError


def _disabled(operation: str) -> RemoteGpuRequiredError:
    return RemoteGpuRequiredError(
        f"local media execution is disabled; submit {operation} to the remote GPU"
    )


async def wait_for_memory_headroom(desc: str = "local media job") -> None:
    raise _disabled(desc)


@asynccontextmanager
async def local_media_slot(desc: str = "local media job"):
    raise _disabled(desc)
    yield  # pragma: no cover


@contextmanager
def local_media_slot_sync(desc: str = "local media job"):
    raise _disabled(desc)
    yield  # pragma: no cover
