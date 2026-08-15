from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "gpu_service"))

from asr_config import ASR_INITIAL_PROMPT, aligned_segment_bounds, transcribe_options


class _Word:
    def __init__(self, start, end):
        self.start = start
        self.end = end


class _Segment:
    def __init__(self, start, end, words=None):
        self.start = start
        self.end = end
        self.words = words


def test_mandarin_live_commerce_options_are_explicit():
    options = transcribe_options()
    assert options["language"] == "zh"
    assert options["beam_size"] >= 5
    assert options["condition_on_previous_text"] is False
    assert options["word_timestamps"] is True
    assert "假发" in ASR_INITIAL_PROMPT
    assert "高温丝" in ASR_INITIAL_PROMPT


def test_retranscription_tool_is_explicitly_opt_in():
    source = Path(__file__).parents[1] / "scripts" / "retranscribe_recording.py"
    text = source.read_text(encoding="utf-8")
    assert "--recording-id" in text
    assert "--reclip" in text
    assert "does not enqueue director" in text
    assert "mark_recording_transcribed" in text
    assert "X-Idempotency-Key" in text


def test_word_edges_remove_vad_padding_from_srt_cue():
    segment = _Segment(10.0, 14.0, [_Word(10.6, 11.2), _Word(12.4, 13.1)])
    assert aligned_segment_bounds(segment) == (10.6, 13.1)


def test_segment_edges_are_fallback_when_word_timestamps_are_missing():
    assert aligned_segment_bounds(_Segment(2.0, 3.5)) == (2.0, 3.5)
