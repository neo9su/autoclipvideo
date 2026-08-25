"""Resolve transcript sidecars safely across recording naming conventions."""
from __future__ import annotations

from pathlib import Path
from typing import Optional
import re


def srt_candidates(mp4_path: str | Path) -> tuple[Path, Path]:
    """Return the supported sidecar names in preferred order."""
    source = Path(mp4_path)
    return (
        source.with_suffix(".srt"),
        Path(f"{source}.srt"),
    )


def resolve_srt_path(mp4_path: str | Path) -> Optional[str]:
    """Return a non-empty SRT sidecar, or ``None`` for missing/empty input.

    Empty files are deliberately rejected: treating an empty transcript as valid
    causes downstream matchers to silently produce unsupported edits.
    """
    for candidate in srt_candidates(mp4_path):
        try:
            if candidate.is_file() and candidate.stat().st_size > 0 and candidate.read_bytes().strip():
                return str(candidate)
        except OSError:
            continue
    return None


def require_srt_path(mp4_path: str | Path) -> str:
    """Resolve a usable sidecar or raise a clear fail-closed error."""
    resolved = resolve_srt_path(mp4_path)
    if resolved is None:
        raise FileNotFoundError(f"No non-empty SRT sidecar for {mp4_path}")
    return resolved


_TIMING = re.compile(r"^(\d\d):(\d\d):(\d\d),(\d{3})\s+-->\s+(\d\d):(\d\d):(\d\d),(\d{3})")


def _srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def offset_srt_text(text: str, offset_seconds: float) -> str:
    """Shift every cue by a global offset without resetting its timeline."""
    if offset_seconds == 0:
        return text

    def replace_timing(match: re.Match[str]) -> str:
        start = (int(match[1]) * 3600 + int(match[2]) * 60 + int(match[3])
                 + int(match[4]) / 1000 + offset_seconds)
        end = (int(match[5]) * 3600 + int(match[6]) * 60 + int(match[7])
               + int(match[8]) / 1000 + offset_seconds)
        return f"{_srt_timestamp(start)} --> {_srt_timestamp(end)}"

    return "\n".join(_TIMING.sub(replace_timing, line) for line in text.splitlines()) + ("\n" if text.endswith("\n") else "")
