"""ASR settings for live-commerce Mandarin transcription.

The GPU service is the only runtime consumer of these settings.  Keep the
model explicit so a deployment can roll back by changing one constant.
"""
from __future__ import annotations

import os


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < 1:
        raise ValueError(f"{name} must be positive")
    return parsed


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized not in {"0", "1", "false", "true"}:
        raise ValueError(f"{name} must be one of 0, 1, false, true")
    return normalized in {"1", "true"}


# large-v3 is the accuracy-first profile for the RTX 4080 SUPER.  Keep all
# overrides explicit and deployment-local so rollback is a service restart.
ASR_MODEL = os.environ.get("ASR_MODEL", "large-v3")
ASR_LANGUAGE = os.environ.get("ASR_LANGUAGE", "zh")
ASR_BEAM_SIZE = _env_int("ASR_BEAM_SIZE", 8)
ASR_BEST_OF = _env_int("ASR_BEST_OF", 5)
ASR_TEMPERATURE = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
ASR_CONDITION_ON_PREVIOUS_TEXT = _env_bool("ASR_CONDITION_ON_PREVIOUS_TEXT", False)
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
        "condition_on_previous_text": ASR_CONDITION_ON_PREVIOUS_TEXT,
        "vad_filter": True,
        "vad_parameters": dict(ASR_VAD_PARAMETERS),
        "word_timestamps": True,
        "without_timestamps": False,
    }
