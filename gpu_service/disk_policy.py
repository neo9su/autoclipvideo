"""Disk admission policy for GPU uploads.

The policy reserves a modest configurable amount of free space and accounts for
an individual upload instead of treating the reserve as a required upload size.
"""

from __future__ import annotations


def required_free_gb(
    upload_size_bytes: int | None,
    minimum_free_gb: float,
    upload_reserve_gb: float,
) -> float:
    """Return the free-space requirement for one upload in GiB."""
    if minimum_free_gb < 0 or upload_reserve_gb < 0:
        raise ValueError("disk free-space settings must be non-negative")
    upload_gb = max(0.0, float(upload_size_bytes or 0)) / (1024 ** 3)
    return max(minimum_free_gb, upload_gb + upload_reserve_gb)


def upload_rejection_reason(
    free_gb: float,
    upload_size_bytes: int | None,
    minimum_free_gb: float,
    upload_reserve_gb: float,
) -> str | None:
    """Explain why an upload cannot be admitted, or return ``None`` when safe."""
    required_gb = required_free_gb(upload_size_bytes, minimum_free_gb, upload_reserve_gb)
    if free_gb >= required_gb:
        return None
    return (
        f"free space {free_gb:.1f} GiB is below the required "
        f"{required_gb:.1f} GiB reserve"
    )


def can_accept_upload(
    free_gb: float,
    upload_size_bytes: int | None,
    minimum_free_gb: float,
    upload_reserve_gb: float,
) -> bool:
    """Return whether the upload can be accepted without exhausting storage."""
    return free_gb >= required_free_gb(upload_size_bytes, minimum_free_gb, upload_reserve_gb)
