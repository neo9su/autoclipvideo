"""Acceptance guards for the GPU-only director artifact boundary."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

from director_video import validate_director_output


def _write_valid_ass() -> str:
    return "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n" \
        "Dialogue: 0,0:00:00.00,0:00:01.00,XQN,,0,0,0,,验收字幕\n"


@pytest.mark.asyncio
async def test_director_artifact_requires_non_empty_subtitles_and_audio(tmp_path):
    output = tmp_path / "final.mp4"
    voiceover = tmp_path / "voice.wav"
    output.write_bytes(b"not-a-video")
    voiceover.write_bytes(b"voice")

    with pytest.raises(RuntimeError, match="probe failed"):
        await validate_director_output(str(output), str(voiceover), _write_valid_ass())


@pytest.mark.asyncio
async def test_director_artifact_rejects_empty_subtitles_before_probe(tmp_path):
    output = tmp_path / "final.mp4"
    voiceover = tmp_path / "voice.wav"
    output.write_bytes(b"placeholder")
    voiceover.write_bytes(b"voice")

    with pytest.raises(RuntimeError, match="subtitles are empty"):
        await validate_director_output(str(output), str(voiceover), "[Events]\n")


def test_api_marks_completion_only_after_artifact_validation():
    source = (Path(__file__).parents[1] / "backend" / "api_v2.py").read_text()
    validation = source.index("artifact_evidence = await validate_director_output")
    completion = source.index("director_status = 2", validation)
    assert validation < completion
    assert "未生成 ASS 字幕内容" in source

