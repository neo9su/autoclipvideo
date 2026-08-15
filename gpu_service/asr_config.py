"""ASR settings for live-commerce Mandarin transcription.

The GPU service is the only runtime consumer of these settings.  Keep the
model explicit so a deployment can roll back by changing one constant.
"""
from __future__ import annotations

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
