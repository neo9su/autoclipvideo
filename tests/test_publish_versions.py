from pathlib import Path

from backend.video_path_resolver import (
    build_content_disposition,
    resolve_artifact_path,
    resolve_publish_video,
)


def test_content_disposition_is_ascii_safe_and_preserves_utf8_name():
    header = build_content_disposition("直出版-测试 视频.mp4")
    assert header.startswith('inline; filename="')
    assert all(ord(char) < 128 for char in header.split("; filename*=")[0])
    assert "filename*=UTF-8''" in header
    assert "%E7%9B%B4%E5%87%BA%E7%89%88" in header


def test_content_disposition_uses_safe_fallback_for_empty_name():
    assert build_content_disposition("") == 'inline; filename="video.mp4"; filename*=UTF-8\'\'video.mp4'


def test_publish_resolver_supports_realistic_and_conservative(tmp_path, monkeypatch):
    import backend.video_path_resolver as resolver

    monkeypatch.setattr(resolver, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(resolver, "RECORDINGS_DIR", tmp_path / "recordings")
    (tmp_path / "recordings").mkdir()
    for name in ("classic.mp4", "director.mp4", "realistic.mp4", "conservative.mp4", "qianchuan.mp4"):
        (tmp_path / "recordings" / name).write_bytes(b"video")

    group = {
        "merged_filename": "classic.mp4",
        "director_final_video": "director.mp4",
        "realistic_final_video": "realistic.mp4",
        "conservative_final_video": "conservative.mp4",
        "qianchuan_final_video": "qianchuan.mp4",
    }
    path, selected, _, available = resolve_publish_video(group, "realistic")
    assert Path(path).name == "realistic.mp4"
    assert selected == "realistic"
    assert set(available) == {"classic", "director", "realistic", "conservative", "qianchuan"}

    for version in ("realistic", "conservative"):
        path, reason = resolve_artifact_path(group[f"{version}_final_video"], version)
        assert Path(path).name == f"{version}.mp4"
        assert reason == "ready"


def test_publish_resolver_keeps_legacy_selection_values(tmp_path, monkeypatch):
    import backend.video_path_resolver as resolver

    monkeypatch.setattr(resolver, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(resolver, "RECORDINGS_DIR", tmp_path / "recordings")
    (tmp_path / "recordings").mkdir()
    (tmp_path / "recordings" / "classic.mp4").write_bytes(b"video")

    path, selected, _, _ = resolve_publish_video({"merged_filename": "classic.mp4"}, "both")
    assert Path(path).name == "classic.mp4"
    assert selected == "classic"

    path, selected, _, _ = resolve_publish_video({"merged_filename": "classic.mp4"}, "creative")
    assert path is None
    assert selected is None
