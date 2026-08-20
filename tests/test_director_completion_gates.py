"""Regression tests for director subtitle and voiceover completion gates."""

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))
from director_video import validate_director_composition_inputs


def _valid_inputs(tmp_path: Path):
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"RIFF-test-audio")
    return ([{"room_id": 1, "filename": "source.mp4"}], str(audio),
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            "Dialogue: 0,0:00:00.00,0:00:01.00,XQN,,0,0,0,,验收字幕",
            [{"scene_id": 1, "duration": 1.0}])


def test_valid_director_inputs_pass(tmp_path):
    validate_director_composition_inputs(*_valid_inputs(tmp_path))


@pytest.mark.parametrize("field", ["audio", "subtitles", "segments"])
def test_missing_delivery_component_is_rejected(tmp_path, field):
    clips, audio, ass, segments = _valid_inputs(tmp_path)
    if field == "audio":
        Path(audio).write_bytes(b"")
    elif field == "subtitles":
        ass = "[Events]"
    else:
        segments = []
    with pytest.raises(ValueError):
        validate_director_composition_inputs(clips, audio, ass, segments)
