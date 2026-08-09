"""Resolve transcript sidecars safely across recording naming conventions."""
from __future__ import annotations

from pathlib import Path
from typing import Optional


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
