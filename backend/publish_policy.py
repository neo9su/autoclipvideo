"""Shared policy for videos submitted to a publishing queue."""

MIN_PUBLISH_DURATION_SECONDS = 15.0
MAX_PUBLISH_DURATION_SECONDS = 300.0


def validate_publish_duration(duration: float) -> str | None:
    """Return a user-facing failure reason, or ``None`` when duration is valid."""
    if duration < MIN_PUBLISH_DURATION_SECONDS:
        return f"时长不足（{duration:.1f}s，需要 ≥ {MIN_PUBLISH_DURATION_SECONDS:.0f} 秒）"
    if duration > MAX_PUBLISH_DURATION_SECONDS:
        return f"时长超限（{duration:.1f}s，需要 ≤ {MAX_PUBLISH_DURATION_SECONDS:.0f} 秒）"
    return None
