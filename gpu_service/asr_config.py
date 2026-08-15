"""Accuracy-first faster-whisper profile for live-commerce Mandarin audio.

The defaults target an RTX 4080 SUPER and are intentionally explicit so an
operator can roll back by setting the documented environment overrides and
restarting the remote GPU service.  This module must not be imported by the
Mac control-plane media workers.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

ASR_MODEL = "large-v3"
ASR_LANGUAGE = "zh"
ASR_BEAM_SIZE = 8
ASR_BEST_OF = 5
ASR_TEMPERATURE = (0.0, 0.2, 0.4, 0.6, 0.8)
ASR_INITIAL_PROMPT = (
    "这是中文普通话直播带货，主题是发型和假发。"
    "假发、刘海、鬓发、头顶、颅顶、发际线、黑长直、自然黑、方圆脸、"
    "显脸小、真人发、高温丝、发缝、贴头皮、蓬松。"
)
ASR_VAD_PARAMETERS = {
    "threshold": 0.35,
    "min_silence_duration_ms": 450,
    "speech_pad_ms": 250,
}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return default if value is None else int(value)


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return default if value is None else float(value)


@dataclass(frozen=True)
class ASRConfig:
    """Validated transcription settings passed directly to faster-whisper."""

    model_name: str = os.getenv("ASR_MODEL", ASR_MODEL)
    language: str = os.getenv("ASR_LANGUAGE", ASR_LANGUAGE)
    beam_size: int = _env_int("ASR_BEAM_SIZE", ASR_BEAM_SIZE)
    best_of: int = _env_int("ASR_BEST_OF", ASR_BEST_OF)
    condition_on_previous_text: bool = os.getenv("ASR_CONDITION_ON_PREVIOUS_TEXT", "0") == "1"
    vad_threshold: float = _env_float("ASR_VAD_THRESHOLD", ASR_VAD_PARAMETERS["threshold"])
    vad_min_silence_ms: int = _env_int("ASR_VAD_MIN_SILENCE_MS", ASR_VAD_PARAMETERS["min_silence_duration_ms"])
    vad_speech_pad_ms: int = _env_int("ASR_VAD_SPEECH_PAD_MS", ASR_VAD_PARAMETERS["speech_pad_ms"])

    def transcribe_options(self) -> dict:
        """Return options that preserve absolute segment timing and context."""
        return {
            "language": self.language,
            "task": "transcribe",
            "beam_size": self.beam_size,
            "best_of": self.best_of,
            "temperature": ASR_TEMPERATURE,
            "initial_prompt": ASR_INITIAL_PROMPT,
            "condition_on_previous_text": self.condition_on_previous_text,
            "vad_filter": True,
            "vad_parameters": {
                "threshold": self.vad_threshold,
                "min_silence_duration_ms": self.vad_min_silence_ms,
                "speech_pad_ms": self.vad_speech_pad_ms,
            },
            "word_timestamps": True,
            "without_timestamps": False,
        }


ASR_CONFIG = ASRConfig()

# Compatibility exports for small operational scripts and older tests.
def transcribe_options() -> dict:
    return ASR_CONFIG.transcribe_options()
