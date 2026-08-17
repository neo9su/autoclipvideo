"""Validated service settings shared by the remote GPU source distribution."""

from __future__ import annotations


def configured_positive_int(environment: dict[str, str], name: str, default: int) -> int:
    """Read a positive integer setting, falling back for bad values."""
    try:
        value = int(environment.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default
