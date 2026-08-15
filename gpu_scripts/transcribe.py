#!/usr/bin/env python3
"""
Transcribe an MP4 file using faster-whisper (large-v3) and output SRT.
Usage: python3 transcribe.py <mp4_file>

Deploy to GPU server: /data/scripts/transcribe.py
Requires: pip install faster-whisper
"""
import sys
import os

try:
    from asr_config import ASR_MODEL, get_asr_config
except ImportError:
    try:
        from gpu_service_src.asr_config import ASR_MODEL, get_asr_config
    except ImportError:
        # The standalone deployment copies this script without the package.
        ASR_MODEL = "large-v3"

        def get_asr_config() -> dict:
            return {
                "language": "zh",
                "initial_prompt": "这是中文直播带货口播，商品是假发。假发、刘海、鬓发、头顶、颅顶、发际线、黑长直、自然黑、方圆脸、显脸小、真人发、高温丝。",
                "beam_size": 8,
                "best_of": 5,
                "temperature": (0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
                "condition_on_previous_text": False,
                "word_timestamps": True,
                "vad_filter": True,
                "vad_parameters": {"threshold": 0.35, "min_silence_duration_ms": 450, "speech_pad_ms": 300},
            }


def fmt_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def aligned_segment_bounds(segment) -> tuple[float, float]:
    """Use word timestamps to avoid VAD padding drifting subtitle edges."""
    words = getattr(segment, "words", None) or []
    starts = [word.start for word in words if word.start is not None]
    ends = [word.end for word in words if word.end is not None]
    start = min(starts, default=segment.start)
    end = max(ends, default=segment.end)
    return max(0.0, start), max(start, end)


def main():
    if len(sys.argv) < 2:
        print("Usage: transcribe.py <mp4_file>")
        sys.exit(1)

    mp4_path = sys.argv[1]
    if not os.path.exists(mp4_path):
        print(f"File not found: {mp4_path}", file=sys.stderr)
        sys.exit(1)

    srt_path = os.path.splitext(mp4_path)[0] + ".srt"

    print(f"Loading faster-whisper {ASR_MODEL} ...")
    from faster_whisper import WhisperModel
    model = WhisperModel(ASR_MODEL, device="cuda", compute_type="float16")

    print(f"Transcribing: {mp4_path}")
    segments, info = model.transcribe(mp4_path, **get_asr_config())

    print(f"Language: {info.language} ({info.language_probability:.2%})")

    with open(srt_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            start, end = aligned_segment_bounds(seg)
            f.write(f"{i}\n")
            f.write(f"{fmt_ts(start)} --> {fmt_ts(end)}\n")
            f.write(f"{seg.text.strip()}\n\n")

    print(f"SRT saved: {srt_path}")


if __name__ == "__main__":
    main()
