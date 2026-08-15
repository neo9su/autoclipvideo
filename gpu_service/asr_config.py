"""Conservative ASR defaults for Mandarin live-commerce audio.

The configuration is intentionally kept in one module so the GPU worker and
the standalone transcriber cannot silently drift apart.  ``large-v3`` fits
the RTX 4080 SUPER deployment and is preferred over smaller Whisper models.
"""
from __future__ import annotations

import os

ASR_MODEL = os.environ.get("ASR_MODEL", "large-v3")
ASR_COMPUTE_TYPE = os.environ.get("ASR_COMPUTE_TYPE", "float16")
ASR_LANGUAGE = os.environ.get("ASR_LANGUAGE", "zh")
ASR_BEAM_SIZE = int(os.environ.get("ASR_BEAM_SIZE", "8"))
ASR_BEST_OF = int(os.environ.get("ASR_BEST_OF", "5"))
ASR_TEMPERATURE = (0.0, 0.2, 0.4, 0.6, 0.8)
ASR_VAD_PARAMETERS = {
    "threshold": 0.3,
    "min_silence_duration_ms": 350,
    "speech_pad_ms": 400,
}

# Whisper's initial_prompt is the supported domain vocabulary hook.  Keep it
# short enough not to bias ordinary speech while covering common wig terms.
ASR_INITIAL_PROMPT = (
    "这是中文普通话直播卖假发。假发，刘海，鬓发，头顶，颅顶，发际线，"
    "黑长直，自然黑，方圆脸，显脸小，真人发，高温丝。"
)


def transcribe_options() -> dict:
    """Return stable faster-whisper options used for every source transcript."""
    return {
        "language": ASR_LANGUAGE,
        "task": "transcribe",
        "beam_size": ASR_BEAM_SIZE,
        "best_of": ASR_BEST_OF,
        "temperature": ASR_TEMPERATURE,
        "condition_on_previous_text": False,
        "initial_prompt": ASR_INITIAL_PROMPT,
        "vad_filter": True,
        "vad_parameters": dict(ASR_VAD_PARAMETERS),
        "word_timestamps": True,
        "without_timestamps": False,
    }


def get_asr_config() -> dict:
    """Backward-compatible name for standalone GPU deployments."""
    return transcribe_options()
