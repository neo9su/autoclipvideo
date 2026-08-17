"""Disk admission policy for GPU uploads.

The policy reserves a small configurable amount of free space and, when the
request size is known, reserves enough space for both the upload and the
configured safety margin.  It intentionally does not use total volume size
as an admission requirement.
"""

from __future__ import annotations


def upload_rejection_reason(
    free_gb: float,
    upload_bytes: int | None,
    *,
    minimum_free_gb: float,
    upload_reserve_gb: float,
) -> str | None:
    """Return a user-safe rejection reason, or ``None`` when upload is safe."""
    if free_gb < minimum_free_gb:
        return f"{free_gb:.1f}GB free, reserve is {minimum_free_gb:.1f}GB"

    if upload_bytes is None or upload_bytes < 0:
        return None

    required_gb = upload_bytes / (1024 ** 3) + upload_reserve_gb
    if free_gb < required_gb:
        return f"{free_gb:.1f}GB free, upload requires {required_gb:.1f}GB including reserve"
    return None
