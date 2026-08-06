"""Resolve publish video paths across migrations without touching completed tasks."""
from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath
from typing import Mapping, Optional


BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
RECORDINGS_DIR = PROJECT_ROOT / "recordings"


def path_basename(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return Path(raw.replace("\\", "/")).name or PureWindowsPath(raw).name


def _candidate_paths(path: object) -> list[Path]:
    raw = str(path or "").strip()
    if not raw:
        return []
    normalized = Path(raw.replace("\\", "/"))
    candidates = [normalized]
    basename = path_basename(raw)
    if basename:
        candidates.extend([
            RECORDINGS_DIR / basename,
            RECORDINGS_DIR / "director_outputs" / basename,
            RECORDINGS_DIR / "creative_outputs" / basename,
            PROJECT_ROOT / "recordings" / "director_outputs" / basename,
        ])
    return candidates


_VERSION_FIELDS = {
    "qianchuan": "qianchuan_final_video",
    "creative": "creative_final_video",
    "director": "director_final_video",
    "classic": "merged_filename",
}


def resolve_publish_video(
    group: Mapping[str, object], requested_version: object = "both"
) -> tuple[Optional[str], Optional[str], list[str], list[str]]:
    """Resolve the file to store in a publish task.

    ``both`` (and an empty selection) means the default publishing policy:
    qianchuan, creative, director, then classic.  An explicit version is
    strict: it is never silently replaced by another version.  The returned
    candidate descriptions and available version names are intended for the
    API's actionable 409 response.
    """
    requested = str(requested_version or "both").strip().lower()
    if requested in ("", "default", "both"):
        versions = ["qianchuan", "creative", "director", "classic"]
    elif requested in _VERSION_FIELDS:
        versions = [requested]
    else:
        versions = []

    checked: list[str] = []
    available: list[str] = []
    resolved: dict[str, str] = {}
    for version in ("qianchuan", "creative", "director", "classic"):
        field = _VERSION_FIELDS[version]
        value = group.get(field)
        if not value:
            checked.append(f"{version}: 未设置")
            continue
        candidates = _candidate_paths(value)
        found = None
        for candidate in candidates:
            checked.append(f"{version}: {candidate}")
            if candidate.is_file():
                found = str(candidate)
                break
        if found:
            resolved[version] = found
            available.append(version)

    for version in versions:
        if version in resolved:
            return resolved[version], version, checked, available
    return None, None, checked, available


def resolve_video_path(video_path: object, group: Optional[Mapping[str, object]] = None) -> tuple[Optional[str], str]:
    """Return a local existing path and reason, preferring current group artifacts."""
    values: list[object] = []
    if group:
        for field in ("qianchuan_final_video", "creative_final_video", "director_final_video"):
            if group.get(field):
                values.append(group[field])
        if group.get("merged_filename"):
            values.append(RECORDINGS_DIR / str(group["merged_filename"]))
    values.append(video_path)

    seen: set[str] = set()
    for value in values:
        for candidate in _candidate_paths(value):
            key = str(candidate)
            if key in seen:
                continue
            seen.add(key)
            if candidate.is_file():
                return str(candidate), "resolved_current_or_migrated_path"

    basename = path_basename(video_path)
    if basename:
        matches = sorted({p for p in RECORDINGS_DIR.rglob(basename) if p.is_file()})
        if len(matches) == 1:
            return str(matches[0]), "resolved_unique_basename"
        if len(matches) > 1:
            return None, f"ambiguous_basename_matches:{len(matches)}"
    if video_path:
        return None, "file_missing_after_path_mapping"
    return None, "no_video_path"


def describe_missing(video_path: object, reason: str) -> str:
    return f"视频文件不可用（{reason}）：{video_path or '未设置路径'}"
