"""Stable ASR settings for Mandarin live-commerce recordings.

The GPU service is intentionally the only place where Whisper runs.  Keeping
the settings in one small module makes model changes auditable and gives
operators a single rollback point.
"""
import os

ASR_MODEL = os.environ.get("ASR_MODEL", "large-v3")
ASR_LANGUAGE = os.environ.get("ASR_LANGUAGE", "zh")
ASR_INITIAL_PROMPT = (
    "这是中文直播带货口播，商品是假发。"
    "假发、刘海、鬓发、头顶、颅顶、发际线、黑长直、自然黑、方圆脸、"
    "显脸小、真人发、高温丝。"
)

# These settings favor stable timestamps over speculative long-range decoding.
# VAD is deliberately conservative enough not to trim consonants at chunk
# boundaries, while word timestamps let faster-whisper refine segment edges.
ASR_TRANSCRIBE_OPTIONS = {
    "language": ASR_LANGUAGE,
    "initial_prompt": ASR_INITIAL_PROMPT,
    "beam_size": int(os.environ.get("ASR_BEAM_SIZE", "8")),
    "best_of": int(os.environ.get("ASR_BEST_OF", "5")),
    "temperature": (0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
    "condition_on_previous_text": os.environ.get("ASR_CONDITION_ON_PREVIOUS_TEXT", "0").lower() in {"1", "true"},
    "word_timestamps": True,
    "vad_filter": True,
    "vad_parameters": {
        "threshold": 0.35,
        "min_silence_duration_ms": 450,
        "speech_pad_ms": 300,
    },
}


def get_model_name() -> str:
    """Return the explicitly selected faster-whisper model name."""
    return ASR_MODEL


def get_asr_config() -> dict:
    """Return a copy so callers cannot mutate process-wide ASR defaults."""
    return {
        **ASR_TRANSCRIBE_OPTIONS,
        "vad_parameters": dict(ASR_TRANSCRIBE_OPTIONS["vad_parameters"]),
    }


def aligned_segment_bounds(segment: object) -> tuple[float, float]:
    """Return speech edges rather than VAD-padded segment edges when present."""
    segment_start = float(getattr(segment, "start", 0.0))
    segment_end = float(getattr(segment, "end", segment_start))
    words = getattr(segment, "words", None) or ()
    valid_words = [
        word for word in words
        if getattr(word, "start", None) is not None
        and getattr(word, "end", None) is not None
    ]
    if not valid_words:
        return segment_start, segment_end
    return float(valid_words[0].start), float(valid_words[-1].end)
