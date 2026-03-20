#!/usr/bin/env python3
"""
Transcribe an MP4 file using faster-whisper (large-v3) and output SRT.
Usage: python3 transcribe.py <mp4_file>

Deploy to GPU server: /data/scripts/transcribe.py
Requires: pip install faster-whisper
"""
import sys
import os


def fmt_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def main():
    if len(sys.argv) < 2:
        print("Usage: transcribe.py <mp4_file>")
        sys.exit(1)

    mp4_path = sys.argv[1]
    if not os.path.exists(mp4_path):
        print(f"File not found: {mp4_path}", file=sys.stderr)
        sys.exit(1)

    srt_path = os.path.splitext(mp4_path)[0] + ".srt"

    print(f"Loading faster-whisper large-v3 ...")
    from faster_whisper import WhisperModel
    model = WhisperModel("large-v3", device="cuda", compute_type="float16")

    print(f"Transcribing: {mp4_path}")
    segments, info = model.transcribe(
        mp4_path,
        language="zh",
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
    )

    print(f"Language: {info.language} ({info.language_probability:.2%})")

    with open(srt_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments, 1):
            f.write(f"{i}\n")
            f.write(f"{fmt_ts(seg.start)} --> {fmt_ts(seg.end)}\n")
            f.write(f"{seg.text.strip()}\n\n")

    print(f"SRT saved: {srt_path}")


if __name__ == "__main__":
    main()
