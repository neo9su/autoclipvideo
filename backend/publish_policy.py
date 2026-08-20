"""Shared policy for videos submitted through the publish queue."""

MIN_PUBLISH_DURATION_SECONDS = 15.0
MAX_PUBLISH_DURATION_SECONDS = 300.0


def validate_publish_duration(duration: object) -> str | None:
    """Return a user-facing rejection reason, or ``None`` when duration is valid."""
    try:
        value = float(duration)
    except (TypeError, ValueError):
        return "视频时长无法读取"

    if value < MIN_PUBLISH_DURATION_SECONDS:
        return f"时长不足（{value:.1f}s，需要 ≥ {MIN_PUBLISH_DURATION_SECONDS:.0f} 秒）"
    if value > MAX_PUBLISH_DURATION_SECONDS:
        return f"时长超限（{value:.1f}s，需要 ≤ {MAX_PUBLISH_DURATION_SECONDS:.0f} 秒）"
    return None
