from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "gpu_service"))

from asr_config import ASR_CONFIG, ASR_INITIAL_PROMPT, transcribe_options


class FakeWord:
    def __init__(self, start, end):
        self.start = start
        self.end = end


class FakeSegment:
    start = 1.0
    end = 4.0
    words = [FakeWord(1.4, 2.0), FakeWord(2.1, 2.8)]


def test_mandarin_live_commerce_options_are_explicit():
    options = transcribe_options()
    assert options["language"] == "zh"
    assert options["beam_size"] >= 5
    assert options["condition_on_previous_text"] is False
    assert options["word_timestamps"] is True
    assert "假发" in ASR_INITIAL_PROMPT
    assert "高温丝" in ASR_INITIAL_PROMPT
    assert ASR_CONFIG.model_name == "large-v3"


def test_word_boundaries_are_used_for_subtitle_edges():
    source = Path(__file__).parents[1] / "gpu_service" / "main.py"
    text = source.read_text(encoding="utf-8")
    assert "_aligned_segment_times" in text
    assert "word.start" in text


def test_retranscription_tool_is_explicitly_opt_in():
    source = Path(__file__).parents[1] / "scripts" / "retranscribe_recording.py"
    text = source.read_text(encoding="utf-8")
    assert "--recording-id" in text
    assert "--reclip" in text
    assert "does not enqueue director" in text
    assert "mark_recording_transcribed" in text
    assert "X-Idempotency-Key" in text


def test_gpu_srt_uses_word_timestamp_edges_when_available():
    source = (Path(__file__).parents[1] / "gpu_service" / "main.py").read_text(encoding="utf-8")
    assert "def _segment_bounds" in source
    assert "_segment_bounds(seg)" in source
