from pathlib import Path

import pytest

from backend.srt_resolver import require_srt_path, resolve_srt_path


def test_resolves_standard_srt_before_mp4_srt(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"mp4")
    standard = tmp_path / "clip.srt"
    sidecar = tmp_path / "clip.mp4.srt"
    standard.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")
    sidecar.write_text("fallback", encoding="utf-8")

    assert resolve_srt_path(video) == str(standard)


def test_resolves_mp4_srt_when_standard_name_is_missing(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"mp4")
    sidecar = tmp_path / "clip.mp4.srt"
    sidecar.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")

    assert resolve_srt_path(video) == str(sidecar)


def test_empty_srt_is_fail_closed(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"mp4")
    (tmp_path / "clip.srt").write_text("   \n", encoding="utf-8")
    (tmp_path / "clip.mp4.srt").write_bytes(b"")

    assert resolve_srt_path(video) is None
    with pytest.raises(FileNotFoundError, match="non-empty SRT"):
        require_srt_path(video)
