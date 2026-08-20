"""Fail-closed release gates for the remote director pipeline."""

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

from director_video import _require_burn_in_and_voiceover, _validate_remote_media_report


def test_release_requires_timed_subtitles_and_non_empty_voiceover(tmp_path: Path):
    audio_path = tmp_path / "voice.wav"
    audio_path.write_bytes(b"wav")

    _require_burn_in_and_voiceover("[Events]\nDialogue: 0:00:00.00,0:00:01.00,Main,,,text", str(audio_path))

    with pytest.raises(RuntimeError, match="subtitle burn-in"):
        _require_burn_in_and_voiceover("[Events]", str(audio_path))
    with pytest.raises(RuntimeError, match="voiceover"):
        _require_burn_in_and_voiceover("Dialogue: 0,0:00:00.00,0:00:01.00,Main,,,text", str(tmp_path / "missing.wav"))


def test_remote_quality_requires_video_audio_and_duration():
    _validate_remote_media_report({"ok": True, "video_streams": 1, "audio_streams": 1, "duration": 30.5,
                                   "subtitle_burned": True, "generated_voiceover_mixed": True})
    with pytest.raises(RuntimeError, match="audio stream"):
        _validate_remote_media_report({"ok": True, "video_streams": 1, "audio_streams": 0, "duration": 30.5})
    with pytest.raises(RuntimeError, match="quality gate"):
        _validate_remote_media_report({"ok": False, "errors": ["decode failed"]})
