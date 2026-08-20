"""Regression tests for mandatory director media inputs and GPU quality gates."""

from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

from director_video import validate_director_media_inputs


def test_director_rejects_missing_subtitles():
    try:
        validate_director_media_inputs("", "valid-audio")
    except ValueError as error:
        assert "subtitles" in str(error)
    else:
        raise AssertionError("missing subtitles must fail the director media gate")


def test_director_rejects_ass_without_dialogue():
    try:
        validate_director_media_inputs("[Script Info]", "valid-audio")
    except ValueError as error:
        assert "subtitles" in str(error)
    else:
        raise AssertionError("ASS without timed dialogue must fail the director media gate")


def test_director_rejects_missing_voiceover():
    try:
        validate_director_media_inputs("Dialogue: 0,0:00:00.00,0:00:01.00,XQN,,,text", "")
    except ValueError as error:
        assert "TTS audio" in str(error)
    else:
        raise AssertionError("missing TTS must fail the director media gate")


def test_gpu_worker_keeps_required_input_guards_and_quality_endpoint():
    source = Path(__file__).parents[1] / "gpu_service" / "main.py"
    text = source.read_text(encoding="utf-8")
    assert 'raise ValueError("director job requires non-empty ASS subtitles")' in text
    assert 'raise ValueError("director job requires TTS audio")' in text
    assert 'or not quality.get("ok")' in (Path(__file__).parents[1] / "backend" / "director_video.py").read_text(encoding="utf-8")
