"""Single source of truth for source-recording duration eligibility."""

import asyncio
import os

MIN_RECORDING_DURATION_SECONDS = 28.0
# Compatibility alias for pipeline modules that use the shorter name.
MIN_RECORDING_DURATION = MIN_RECORDING_DURATION_SECONDS
TOO_SHORT_REASON = "too_short"
UNAVAILABLE_REASON = "duration_unavailable"


def classify_duration(duration: object) -> str:
    """Return an explicit status; invalid or absent values are never eligible."""
    try:
        value = float(duration)
    except (TypeError, ValueError):
        return UNAVAILABLE_REASON
    if value != value or value <= 0 or value in (float("inf"), float("-inf")):
        return UNAVAILABLE_REASON
    return "accepted" if value >= MIN_RECORDING_DURATION_SECONDS else TOO_SHORT_REASON


def is_processable_duration(duration: object) -> bool:
    return classify_duration(duration) == "accepted"


async def probe_duration(path: str) -> float | None:
    """Probe a media file without treating probe failure as a short file."""
    if not path or not os.path.isfile(path):
        return None
    try:
        process = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await process.communicate()
        if process.returncode != 0:
            return None
        value = float(stdout.decode().strip())
        return value if is_processable_probe(value) else None
    except (OSError, ValueError):
        return None


def is_processable_probe(value: object) -> bool:
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return False
    return numeric_value > 0 and numeric_value not in (float("inf"), float("-inf"))


def duration_reason(duration: object) -> str:
    status = classify_duration(duration)
    if status == TOO_SHORT_REASON:
        return f"时长不足（{float(duration):.2f}秒 < {MIN_RECORDING_DURATION_SECONDS:.0f}秒）"
    if status == UNAVAILABLE_REASON:
        return "时长不可用（媒体探测失败或缺失）"
    return ""
