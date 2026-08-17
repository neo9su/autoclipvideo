from pathlib import Path

import pytest

from backend import media_contract
from backend.director_matcher import SemanticMatcher


def test_resolve_windows_non_ascii_relative_media_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(media_contract, "STORAGE_DIR", tmp_path)
    media = tmp_path / "素材" / "源视频.mp4"
    media.parent.mkdir()
    media.write_bytes(b"video")

    assert media_contract.resolve_media_file(r"素材\源视频.mp4") == media
    assert media_contract.resolve_media_file(r"C:\素材\源视频.mp4") is None
    assert media_contract.resolve_media_file(r"素材\..\other.mp4") is None


def test_resolve_srt_for_recording_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(media_contract, "STORAGE_DIR", tmp_path)
    source = tmp_path / "素材" / "源视频.mp4"
    source.parent.mkdir()
    source.write_bytes(b"video")
    sidecar = Path(f"{source}.srt")
    sidecar.write_text("1\n00:00:00,000 --> 00:00:03,000\n原始字幕\n", encoding="utf-8")

    assert media_contract.resolve_srt_file(r"素材\源视频.mp4") == sidecar


@pytest.mark.asyncio
async def test_source_srt_fallback_when_strict_matching_has_no_candidate() -> None:
    matcher = object.__new__(SemanticMatcher)
    matcher.model = None

    async def recordings(_group_id: int):
        return [{
            "recording_id": 7,
            "duration": 8.0,
            "srt_entries": [{"idx": 1, "start": 1.0, "end": 4.0, "text": "原始字幕"}],
            "transcript_text": "原始字幕",
        }]

    matcher._get_group_recordings = recordings
    matches = await matcher.match_segments_to_recordings(
        [{"scene_id": 1, "voiceover_text": "完全不同的脚本文案", "duration": 2.0}], 4663
    )

    assert len(matches) == 1
    assert matches[0]["match_reason"] == "source_srt_fallback"
    assert matches[0]["matched_source_text"] == "原始字幕"


@pytest.mark.asyncio
async def test_absent_source_media_and_srt_is_explicitly_reported() -> None:
    matcher = object.__new__(SemanticMatcher)
    matcher.model = None

    async def recordings(_group_id: int):
        return []

    matcher._get_group_recordings = recordings
    assert await matcher.match_segments_to_recordings(
        [{"voiceover_text": "脚本", "duration": 2.0}], 4663
    ) == []
    assert "no usable source media/SRT" in matcher.match_error


@pytest.mark.asyncio
async def test_synced_transcribed_source_is_eligible_without_clip_artifact() -> None:
    """A policy-blocked optional thumbnail must not hide a valid source SRT."""
    matcher = object.__new__(SemanticMatcher)
    matcher.model = None

    async def recordings(_group_id: int):
        return [{
            "recording_id": 7172,
            "duration": 42.0,
            "clip_filename": None,
            "thumbnail": None,
            "transcribed": 2,
            "synced": 1,
            "clip_error": "local media execution is disabled: thumbnail generation",
            "srt_entries": [{"idx": 1, "start": 1.0, "end": 6.0, "text": "最终效果展示"}],
            "transcript_text": "最终效果展示",
        }]

    matcher._get_group_recordings = recordings
    matches = await matcher.match_segments_to_recordings(
        [{"scene_id": 1, "voiceover_text": "最终效果", "duration": 4.0}], 4663
    )

    assert matches
    assert matches[0]["matched_recording_id"] == 7172
