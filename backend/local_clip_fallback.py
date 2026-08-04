"""Remote GPU-only compatibility entrypoint for legacy local clip fallback."""

from gpu_execution import reject_local_media


async def fast_local_clip(*args, **kwargs):
    """Reject legacy local encoding instead of silently processing media locally."""
    del args, kwargs
    reject_local_media("legacy local clip encoder")
    return False
