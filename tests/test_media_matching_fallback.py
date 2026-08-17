from pathlib import Path

import pytest

from backend import media_contract
from backend.director_matcher import SemanticMatcher, qianchuan_source_eligibility_sql


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


def test_qianchuan_eligibility_keeps_thumbnail_only_failure_source() -> None:
    predicate = qianchuan_source_eligibility_sql("r")
    assert "r.synced = 1" in predicate
    assert "r.transcribed = 2" in predicate
    assert "r.duration_status = 'accepted'" in predicate
    assert "r.local_deleted = 0" in predicate
    assert "thumbnail generation" in predicate
    assert "r.clipped = 2" in predicate


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
async def test_matcher_error_reporting_survives_lightweight_matcher_construction() -> None:
    """Error reporting must work for recovery-created matcher instances too."""
    matcher = object.__new__(SemanticMatcher)
    matcher.model = None

    async def recordings(_group_id: int):
        return []

    matcher._get_group_recordings = recordings
    matches = await matcher.match_segments_to_recordings(
        [{"scene_id": 1, "voiceover_text": "脚本", "duration": 2.0}], 2088
    )

    assert matches == []
    assert matcher.match_error == (
        "group 2088 has no usable source media/SRT; "
        "verify the recording row and non-empty source sidecar"
    )


@pytest.mark.asyncio
async def test_thumbnail_only_failure_remains_visible_to_qianchuan_matching() -> None:
    import sys

    import backend.director_matcher as director_matcher_module
    import backend.media_contract as media_contract_module

    sys.modules.setdefault("director_matcher", director_matcher_module)
    sys.modules.setdefault("media_contract", media_contract_module)
    from backend.qianchuan_matcher import QianchuanMatcher

    matcher = object.__new__(QianchuanMatcher)
    matcher.model = None

    async def recordings(_group_id: int):
        return [{
            "recording_id": 7172,
            "duration": 12.0,
            "srt_entries": [{"idx": 1, "start": 1.0, "end": 6.0, "text": "自然发型效果"}],
            "transcript_text": "自然发型效果",
            "thumbnail_optional": True,
        }]

    matcher._get_group_recordings = recordings
    matches = await matcher.match_qianchuan_segments(
        [{"scene_id": 1, "voiceover_text": "完全不同的脚本文案", "duration": 2.0}], 4663
    )

    assert len(matches) == 1
    assert matches[0]["matched_recording_id"] == 7172
    assert matches[0]["matched_source_text"] == "自然发型效果"
