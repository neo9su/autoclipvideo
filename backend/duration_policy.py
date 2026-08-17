"""Single source of truth for source-recording duration eligibility."""

MIN_RECORDING_DURATION_SECONDS = 28.0
TOO_SHORT_REASON = "too_short"
UNAVAILABLE_REASON = "duration_unavailable"


def classify_duration(duration: object) -> str:
    """Return an explicit status; invalid or absent values are never eligible."""
    try:
        value = float(duration)
    except (TypeError, ValueError):
        return UNAVAILABLE_REASON
    if value != value or value <= 0:
        return UNAVAILABLE_REASON
    return "accepted" if value >= MIN_RECORDING_DURATION_SECONDS else TOO_SHORT_REASON


def is_processable_duration(duration: object) -> bool:
    return classify_duration(duration) == "accepted"


def duration_reason(duration: object) -> str:
    status = classify_duration(duration)
    if status == TOO_SHORT_REASON:
        return f"时长不足（{float(duration):.2f}秒 < {MIN_RECORDING_DURATION_SECONDS:.0f}秒）"
    if status == UNAVAILABLE_REASON:
        return "时长不可用（媒体探测失败或缺失）"
    return ""
