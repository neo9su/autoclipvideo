"""Auditable media-storage contract for the GPU backend.

The API reports container paths only. A host path is never rewritten into a
Windows or SMB path: the compose volume is the only boundary between the host
and the worker container.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STORAGE_DIR = Path(os.environ.get("STORAGE_DIR", str(PROJECT_ROOT / "recordings"))).expanduser()


def resolve_media_file(filename: str) -> Path | None:
    """Resolve a basename below STORAGE_DIR, rejecting traversal and aliases."""
    candidate_name = Path(str(filename).replace("\\", "/"))
    if candidate_name.is_absolute() or candidate_name.name != str(candidate_name):
        return None
    candidate = (STORAGE_DIR / candidate_name).resolve()
    try:
        candidate.relative_to(STORAGE_DIR.resolve())
    except ValueError:
        return None
    return candidate


def srt_candidates(mp4_path: Path) -> tuple[Path, ...]:
    """Return supported sidecar names without inventing a remote host path."""
    return (mp4_path.with_suffix(".srt"), Path(f"{mp4_path}.srt"))


def audit_media_file(filename: str) -> dict[str, Any]:
    """Return size/readability evidence for one mounted MP4 and its SRT."""
    mp4_path = resolve_media_file(filename)
    if mp4_path is None:
        return {"filename": filename, "valid_filename": False, "mp4": {"readable": False}, "srt": {"readable": False}}
    mp4_readable = mp4_path.is_file() and os.access(mp4_path, os.R_OK)
    srt_path = next((path for path in srt_candidates(mp4_path) if path.is_file()), None)
    srt_readable = bool(srt_path and os.access(srt_path, os.R_OK) and srt_path.stat().st_size > 0)
    mp4_size = mp4_path.stat().st_size if mp4_readable else 0
    srt_size = srt_path.stat().st_size if srt_readable else 0
    return {
        "filename": filename,
        "valid_filename": True,
        "mp4": {"path": str(mp4_path), "readable": mp4_readable, "size_bytes": mp4_size},
        "srt": {"path": str(srt_path) if srt_path else None, "readable": srt_readable, "size_bytes": srt_size},
        "ready": mp4_readable and srt_readable,
    }


def storage_contract() -> dict:
    """Describe mounted storage in terms safe for deployment diagnostics."""
    root = STORAGE_DIR.resolve()
    return {
        "storage_dir": str(root),
        "storage_dir_exists": root.is_dir(),
        "storage_dir_readable": os.access(root, os.R_OK),
        "path_namespace": "container-only",
        "host_path_mapping_required": True,
        "smb_path_translation": False,
    }
