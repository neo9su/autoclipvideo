"""ASR settings for live-commerce Mandarin transcription.

The GPU service is the only runtime consumer of these settings.  Keep the
model explicit so a deployment can roll back by changing one constant.
"""
from __future__ import annotations

import math

ASR_MODEL = "large-v3"
ASR_LANGUAGE = "zh"
ASR_BEAM_SIZE = 8
ASR_BEST_OF = 5
ASR_TEMPERATURE = (0.0, 0.2, 0.4, 0.6, 0.8)
ASR_INITIAL_PROMPT = (
    "这是中文直播带货，主题是发型和假发。"
    "假发、刘海、鬓发、头顶、颅顶、发际线、黑长直、自然黑、方圆脸、"
    "显脸小、真人发、高温丝。"
)
ASR_VAD_PARAMETERS = {
    "threshold": 0.35,
    "min_silence_duration_ms": 450,
    "speech_pad_ms": 250,
}


def transcribe_options() -> dict:
    """Return conservative, alignment-friendly faster-whisper options."""
    return {
        "language": ASR_LANGUAGE,
        "task": "transcribe",
        "beam_size": ASR_BEAM_SIZE,
        "best_of": ASR_BEST_OF,
        "temperature": ASR_TEMPERATURE,
        "initial_prompt": ASR_INITIAL_PROMPT,
        "condition_on_previous_text": False,
        "vad_filter": True,
        "vad_parameters": dict(ASR_VAD_PARAMETERS),
        "word_timestamps": True,
        "without_timestamps": False,
    }


def aligned_segment_bounds(segment: object) -> tuple[float, float]:
    """Use word edges for SRT cues when faster-whisper provides them.

    VAD and decoder segments can include padding around speech.  Word-level
    edges remove that padding without making alignment depend on a word list
    being present (older model/runtime combinations may omit it).
    """
    segment_start = _finite_timestamp(getattr(segment, "start", 0.0), 0.0)
    segment_end = _finite_timestamp(getattr(segment, "end", segment_start), segment_start)
    segment_start = max(0.0, segment_start)
    segment_end = max(segment_start, segment_end)
    words = getattr(segment, "words", None) or ()
    valid_words = [
        word for word in words
        if getattr(word, "start", None) is not None
        and getattr(word, "end", None) is not None
    ]
    if not valid_words:
        return segment_start, segment_end
    word_start = _finite_timestamp(valid_words[0].start, segment_start)
    word_end = _finite_timestamp(valid_words[-1].end, segment_end)
    return max(0.0, word_start), max(word_start, word_end)


def _finite_timestamp(value: object, fallback: float) -> float:
    """Return a finite timestamp without allowing malformed model output into SRT."""
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return fallback
    return timestamp if math.isfinite(timestamp) else fallback
