"""Single source of truth for recording duration eligibility."""
from __future__ import annotations

import math
from typing import Any

MIN_RECORDING_DURATION = 28.0


def classify_duration(value: Any) -> str:
    """Return ``accepted``, ``too_short`` or ``unavailable`` conservatively."""
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return "unavailable"
    if not math.isfinite(duration) or duration < 0:
        return "unavailable"
    return "accepted" if duration >= MIN_RECORDING_DURATION else "too_short"


def duration_reason(value: Any) -> str | None:
    status = classify_duration(value)
    if status == "too_short":
        return "too_short"
    if status == "unavailable":
        return "duration_unavailable"
    return None


def is_processable_duration(value: Any) -> bool:
    return classify_duration(value) == "accepted"
