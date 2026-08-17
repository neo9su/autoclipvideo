"""Single source of truth for source-recording duration eligibility."""

import asyncio
import os

MIN_RECORDING_DURATION = 28.0
TOO_SHORT_REASON = "too_short"
UNAVAILABLE_REASON = "duration_unavailable"

def classify_duration(duration: object) -> tuple[str, str | None]:
    """Classify a probed duration; invalid values are never treated as short."""
    try:
        value = float(duration)
    except (TypeError, ValueError):
        return "unavailable", UNAVAILABLE_REASON
    if value != value or value <= 0 or value == float("inf") or value == float("-inf"):
        return "unavailable", UNAVAILABLE_REASON
    if value < MIN_RECORDING_DURATION:
        return "too_short", TOO_SHORT_REASON
    return "eligible", None


def is_processable_duration(duration: object) -> bool:
    """Return whether a recording is safe to enter any processing queue."""
    status, _ = classify_duration(duration)
    return status == "eligible"


async def probe_duration(path: str) -> float | None:
    """Probe media duration, returning None on missing/invalid media."""
    if not path or not os.path.isfile(path):
        return None
    try:
        process = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await process.communicate()
        if process.returncode != 0:
            return None
        duration = float(stdout.decode().strip())
        return duration if duration > 0 else None
    except (OSError, ValueError):
        return None


async def update_duration(db, recording_id: int, path: str) -> tuple[str, str | None, float | None]:
    """Probe and persist eligibility metadata for one recording."""
    duration = await probe_duration(path)
    status, reason = classify_duration(duration)
    await db.execute(
        "UPDATE recordings SET duration_seconds=?, duration_status=?, skip_reason=? WHERE id=?",
        (duration, status, reason, recording_id),
    )
    return status, reason, duration


def inventory_row(row: dict) -> dict:
    """Return a stable, operator-facing inventory representation."""
    return {
        "recording_id": row.get("id"),
        "path": row.get("filename"),
        "duration_seconds": row.get("duration_seconds"),
        "size_bytes": row.get("size_bytes") or 0,
        "status": row.get("duration_status") or "unavailable",
        "reason": row.get("skip_reason") or UNAVAILABLE_REASON,
    }
