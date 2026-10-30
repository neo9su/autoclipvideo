"""Resolve publish video paths across migrations without touching completed tasks."""
from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath
from typing import Mapping, Optional
from urllib.parse import quote


BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
RECORDINGS_DIR = PROJECT_ROOT / "recordings"


def path_basename(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return Path(raw.replace("\\", "/")).name or PureWindowsPath(raw).name


def build_content_disposition(filename: object) -> str:
    """Build a safe inline disposition for filenames from recording metadata.

    Starlette rejects response headers containing non-Latin-1 characters. Keep
    the legacy filename parameter ASCII-only and carry the original name in
    RFC 5987's UTF-8 ``filename*`` parameter.
    """
    basename = path_basename(filename) or "video.mp4"
    ascii_name = basename.encode("ascii", "ignore").decode("ascii")
    ascii_name = "".join(char if char.isalnum() or char in "._-" else "_" for char in ascii_name)
    if not ascii_name or ascii_name in {".", ".."}:
        ascii_name = "video.mp4"
    if "." not in ascii_name:
        ascii_name += ".mp4"
    encoded_name = quote(basename, safe="._-")
    return f'inline; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded_name}'


def _candidate_paths(path: object) -> list[Path]:
    raw = str(path or "").strip()
    if not raw:
        return []
    normalized = Path(raw.replace("\\", "/"))
    candidates = []
    if normalized.is_absolute():
        candidates.append(normalized)
    else:
        # Database values have historically been a mix of recordings-relative
        # paths, project-relative paths, and absolute paths.  Never resolve a
        # relative artifact against the process cwd (which differs between the
        # API and worker services).
        candidates.extend((RECORDINGS_DIR / normalized, PROJECT_ROOT / normalized))
    basename = path_basename(raw)
    if basename:
        candidates.append(RECORDINGS_DIR / basename)
    return candidates


_VERSION_FIELDS = {
    "qianchuan": "qianchuan_final_video",
    "creative": "creative_final_video",
    "director": "director_final_video",
    "classic": "merged_filename",
    "realistic": "realistic_final_video",
    "conservative": "conservative_final_video",
}


def resolve_artifact_path(value: object, version: str) -> tuple[Optional[str], str]:
    """Resolve one version's database path without borrowing another artifact."""
    if not value:
        return None, "not_generated"
    if version not in _VERSION_FIELDS and version != "qianchuan_preview":
        return None, "invalid_version"
    for candidate in _candidate_paths(value):
        if candidate.is_file():
            return str(candidate), "ready"
    return None, "stale_path"


def resolve_publish_video(
    group: Mapping[str, object], requested_version: object = "both"
) -> tuple[Optional[str], Optional[str], list[str], list[str]]:
    """An explicit version never borrows another version's artifact."""
    requested = str(requested_version or "both").strip().lower()
    versions = list(_VERSION_FIELDS) if requested in ("", "default", "both") else [requested] if requested in _VERSION_FIELDS else []
    checked: list[str] = []
    available: list[str] = []
    resolved: dict[str, str] = {}
    for version, field in _VERSION_FIELDS.items():
        path, status = resolve_artifact_path(group.get(field), version)
        checked.append(f"{version}: {status}")
        if path:
            resolved[version] = path
            available.append(version)
    for version in versions:
        if version in resolved:
            return resolved[version], version, checked, available
    return None, None, checked, available


def resolve_video_path(video_path: object, group: Optional[Mapping[str, object]] = None) -> tuple[Optional[str], str]:
    """Preserve the task's chosen artifact; migrate only the same filename."""
    raw = str(video_path or "").strip()
    if not raw:
        if group:
            path, _, _, _ = resolve_publish_video(group)
            if path:
                return path, "resolved_default_version"
        return None, "not_generated"
    # Old tasks sometimes stored a version name in place of a filename.
    if raw in _VERSION_FIELDS:
        return resolve_artifact_path((group or {}).get(_VERSION_FIELDS[raw]), raw)
    candidates = _candidate_paths(raw)
    # A still-existing selected file always wins over every group artifact.
    normalized = str(Path(raw.replace("\\", "/")))
    for candidate in candidates:
        if str(candidate) == normalized and candidate.is_file():
            return str(candidate), "resolved_selected_path"
    basename = path_basename(raw)
    matching = list(dict.fromkeys(
        str(value) for field in _VERSION_FIELDS.values()
        if (value := (group or {}).get(field)) and path_basename(value) == basename
    ))
    if len(matching) > 1:
        return None, "ambiguous_path"
    # Only the selected filename can be recovered from historical roots or a
    # matching group path. Never replace it with a different version/file.
    if matching:
        candidates.extend(_candidate_paths(matching[0]))
    found = list(dict.fromkeys(str(p) for p in candidates if p.is_file()))
    if len(found) > 1:
        return None, "ambiguous_path"
    if found:
        return found[0], "resolved_same_filename_migration"
    return None, "stale_path"


def describe_missing(video_path: object, reason: str) -> str:
    return f"视频文件不可用（{reason}）：{video_path or '未设置路径'}"
