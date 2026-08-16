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
    candidates = []
    if normalized.is_absolute():
        candidates.append(normalized)
    else:
        # Database values have historically been a mix of recordings-relative
        # paths, project-relative paths, and absolute paths.  Never resolve a
        # relative artifact against the process cwd (which differs between the
        # API and worker services).
        # A value beginning with ``recordings/`` is already project-relative;
        # avoid producing the historical ``recordings/recordings/...`` path.
        if normalized.parts and normalized.parts[0].lower() == RECORDINGS_DIR.name.lower():
            candidates.append(PROJECT_ROOT / normalized)
        else:
            candidates.append(RECORDINGS_DIR / normalized)
            candidates.append(PROJECT_ROOT / normalized)
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
    """Resolve the file to store in a publish task.

    ``both`` (and an empty selection) means the default publishing policy:
    qianchuan, creative, director, then classic.  An explicit version is
    strict: it is never silently replaced by another version.  The returned
    candidate descriptions and available version names are intended for the
    API's actionable 409 response.
    """
    requested = str(requested_version or "both").strip().lower()
    if requested in ("", "default", "both"):
        versions = ["qianchuan", "realistic", "conservative", "creative", "director", "classic"]
    elif requested in _VERSION_FIELDS:
        versions = [requested]
    else:
        versions = []

    checked: list[str] = []
    available: list[str] = []
    resolved: dict[str, str] = {}
    for version in ("qianchuan", "realistic", "conservative", "creative", "director", "classic"):
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
        for field in ("qianchuan_final_video", "realistic_final_video", "conservative_final_video", "creative_final_video", "director_final_video"):
            if group.get(field):
                values.append(group[field])
        if group.get("merged_filename"):
            values.append(group["merged_filename"])
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

    if video_path:
        return None, "stale_path"
    return None, "not_generated"


def describe_missing(video_path: object, reason: str) -> str:
    return f"视频文件不可用（{reason}）：{video_path or '未设置路径'}"
