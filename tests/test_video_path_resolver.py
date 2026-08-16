"""Regression tests for legacy and versioned artifact path normalization."""

from pathlib import Path

import video_path_resolver


def test_retry_version_selection_can_preserve_the_other_style():
    from main import _requested_publish_versions

    assert _requested_publish_versions({"version": "realistic"}) == ["realistic"]
    assert _requested_publish_versions({"versions": ["conservative", "conservative"]}) == ["conservative"]
    assert _requested_publish_versions({}) == ["realistic", "conservative"]


def test_resolves_windows_relative_clip_with_non_ascii_filename(tmp_path, monkeypatch):
    recordings = tmp_path / "recordings"
    target = recordings / "subdir" / "发型展示.mp4"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"video")
    monkeypatch.setattr(video_path_resolver, "RECORDINGS_DIR", recordings)
    monkeypatch.setattr(video_path_resolver, "PROJECT_ROOT", tmp_path)

    resolved, reason = video_path_resolver.resolve_artifact_path(
        r"subdir\发型展示.mp4", "classic"
    )

    assert resolved == str(target)
    assert reason == "ready"


def test_versioned_artifacts_do_not_fall_back_to_another_version(tmp_path, monkeypatch):
    recordings = tmp_path / "recordings"
    realistic = recordings / "realistic" / "clip.mp4"
    realistic.parent.mkdir(parents=True)
    realistic.write_bytes(b"realistic")
    monkeypatch.setattr(video_path_resolver, "RECORDINGS_DIR", recordings)
    monkeypatch.setattr(video_path_resolver, "PROJECT_ROOT", tmp_path)

    missing, reason = video_path_resolver.resolve_artifact_path(
        r"conservative\clip.mp4", "conservative"
    )

    assert missing is None
    assert reason == "stale_path"
