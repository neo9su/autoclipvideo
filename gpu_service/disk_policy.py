"""Pure disk-space policy helpers used by the GPU service upload boundary."""

from __future__ import annotations


def has_upload_capacity(
    free_gb: float,
    file_size_bytes: int | None,
    minimum_free_gb: float,
    headroom_gb: float,
) -> bool:
    """Return whether an upload can be accepted without exhausting storage."""
    if free_gb < 0 or minimum_free_gb < 0 or headroom_gb < 0:
        return False
    upload_gb = (file_size_bytes or 0) / (1024**3)
    required_free_gb = max(minimum_free_gb, upload_gb + headroom_gb)
    return free_gb >= required_free_gb
