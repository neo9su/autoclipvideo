"""Single source of truth for recording eligibility."""

from dataclasses import dataclass
from typing import Optional

MIN_RECORDING_DURATION = 28.0
TOO_SHORT_REASON = "too_short"
DURATION_UNAVAILABLE_REASON = "duration_unavailable"


@dataclass(frozen=True)
class DurationDecision:
    eligible: bool
    status: str
    reason: Optional[str]


def classify_duration(duration: object) -> DurationDecision:
    """Classify a probed duration; unknown/invalid values are never eligible."""
    try:
        seconds = float(duration)
    except (TypeError, ValueError):
        seconds = 0.0
    if seconds <= 0:
        return DurationDecision(False, "unavailable", DURATION_UNAVAILABLE_REASON)
    if seconds < MIN_RECORDING_DURATION:
        return DurationDecision(False, "too_short", TOO_SHORT_REASON)
    return DurationDecision(True, "valid", None)
