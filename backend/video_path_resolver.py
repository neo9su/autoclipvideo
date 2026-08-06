"""Resolve persisted media paths without binding orphan output files."""
from __future__ import annotations

from pathlib import Path, PureWindowsPath
from typing import Mapping, Optional

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
RECORDINGS_DIR = PROJECT_ROOT / "recordings"
_VERSION_FIELDS = {
    "qianchuan": "qianchuan_final_video",
    "creative": "creative_final_video",
    "director": "director_final_video",
    "classic": "merged_filename",
}
_VERSION_ORDER = ("qianchuan", "creative", "director", "classic")


def path_basename(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return Path(raw.replace("\\", "/")).name or PureWindowsPath(raw).name


def _candidate_paths(value: object) -> list[Path]:
    raw = str(value or "").strip()
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
        ])
    return candidates


def resolve_artifact_path(value: object) -> tuple[Optional[str], list[str]]:
    """Resolve only explicitly persisted paths; never search orphan outputs."""
    checked: list[str] = []
    for candidate in _candidate_paths(value):
        checked.append(str(candidate))
        if candidate.is_file():
            return str(candidate), checked
    return None, checked


def resolve_publish_video(
    group: Mapping[str, object], requested_version: object = "both"
) -> tuple[Optional[str], Optional[str], list[str], list[str]]:
    """Resolve an existing artifact using strict explicit or fallback selection."""
    requested = str(requested_version or "both").strip().lower()
    versions = [_VERSION_ORDER] if requested in ("", "default", "both") else [[requested]]
    selected_order = versions[0] if requested in ("", "default", "both") else versions[0]
    checked: list[str] = []
    available: list[str] = []
    resolved: dict[str, str] = {}
    for version in _VERSION_ORDER:
        field = _VERSION_FIELDS[version]
        value = group.get(field)
        if not value:
            checked.append(f"{version}: 未设置 ({field})")
            continue
        path, paths = resolve_artifact_path(value)
        checked.extend(f"{version}: {item}" for item in paths)
        if path:
            resolved[version] = path
            available.append(version)
    for version in selected_order:
        if version in resolved:
            return resolved[version], version, checked, available
    return None, requested, checked, available


def resolve_video_path(video_path: object, group: Optional[Mapping[str, object]] = None) -> tuple[Optional[str], str]:
    """Legacy scheduler resolver; it only returns files that exist."""
    if group:
        path, _, _, _ = resolve_publish_video(group, group.get("publish_versions", "both"))
        if path:
            return path, "resolved_current_or_migrated_path"
    path, checked = resolve_artifact_path(video_path)
    if path:
        return path, "resolved_current_or_migrated_path"
    return None, f"file_missing_after_path_mapping; checked={len(checked)}" if video_path else "no_video_path"


def describe_missing(video_path: object, reason: str) -> str:
    return f"视频文件不可用（{reason}）：{video_path or '未设置路径'}"
