"""Shared policy for videos submitted to a publishing queue.

The constants live in :mod:`duration_policy`, which is also used by the
recording pipeline.  Re-exporting them here keeps publisher imports explicit
without creating a second, drifting duration policy.
"""

import math

from duration_policy import PUBLISH_MAX_DURATION_SECONDS, PUBLISH_MIN_DURATION_SECONDS

MIN_PUBLISH_DURATION_SECONDS = PUBLISH_MIN_DURATION_SECONDS
MAX_PUBLISH_DURATION_SECONDS = PUBLISH_MAX_DURATION_SECONDS


def validate_publish_duration(duration: float) -> str | None:
    """Return a user-facing failure reason, or ``None`` when duration is valid."""
    try:
        duration = float(duration)
    except (TypeError, ValueError):
        return "时长不可用（媒体探测失败或缺失）"
    if not math.isfinite(duration) or duration <= 0:
        return "时长不可用（媒体探测失败或缺失）"
    if duration < MIN_PUBLISH_DURATION_SECONDS:
        return f"时长不足（{duration:.1f}s，需要 ≥ {MIN_PUBLISH_DURATION_SECONDS:.0f} 秒）"
    if duration > MAX_PUBLISH_DURATION_SECONDS:
        return f"时长超限（{duration:.1f}s，需要 ≤ {MAX_PUBLISH_DURATION_SECONDS:.0f} 秒）"
    return None
