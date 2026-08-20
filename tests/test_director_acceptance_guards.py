import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

from director_video import validate_director_acceptance_payload


TIMED_ASS = "Dialogue: 0,0:00:00.30,0:00:01.30,XQN,,0,0,0,,字幕"


def test_director_acceptance_requires_timed_subtitle_and_tts():
    audio = base64.b64encode(b"RIFF-test-audio").decode()
    validate_director_acceptance_payload(TIMED_ASS, audio)


def test_director_acceptance_rejects_missing_subtitle():
    with pytest.raises(ValueError, match="subtitles"):
        validate_director_acceptance_payload("[Events]\n", base64.b64encode(b"audio").decode())


def test_director_acceptance_rejects_missing_tts():
    with pytest.raises(ValueError, match="TTS"):
        validate_director_acceptance_payload(TIMED_ASS, "")


def test_director_acceptance_rejects_invalid_tts():
    with pytest.raises(ValueError, match="base64"):
        validate_director_acceptance_payload(TIMED_ASS, "not base64")
