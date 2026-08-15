from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "gpu_service"))

from asr_config import ASR_INITIAL_PROMPT, transcribe_options


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
