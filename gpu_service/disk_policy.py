"""Disk admission policy for GPU service uploads and output jobs."""

from __future__ import annotations


def configured_positive_float(environment: dict[str, str], name: str, default: float) -> float:
    """Read a positive floating-point setting, falling back for bad values."""
    try:
        value = float(environment.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def configured_positive_int(environment: dict[str, str], name: str, default: int) -> int:
    """Read a positive integer setting without making startup fragile."""
    try:
        value = int(environment.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def required_free_gb(requested_bytes: int | None, minimum_free_gb: float, upload_reserve_gb: float) -> float:
    """Return the free-space floor for one upload."""
    requested_gb = max(0, requested_bytes or 0) / (1024**3)
    return max(minimum_free_gb, requested_gb + upload_reserve_gb)
