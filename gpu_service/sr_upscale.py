"""
Video super-resolution via Real-ESRGAN (spandrel).

Standalone usage:
    python sr_upscale.py input.mp4 output.mp4

Importable function:
    from sr_upscale import load_sr_model, upscale_file
    model = load_sr_model()
    upscale_file(model, "in.mp4", "out.mp4", target_w=1080, target_h=1920)
"""
import argparse
import os
import subprocess
import sys
from typing import Callable, Optional

import cv2
import numpy as np
import torch
import spandrel

MODEL_PATH = r"C:\Users\neo\douyin_processor\models\RealESRGAN_x4plus.pth"
BATCH_SIZE = 2  # reduced from 8 to lower peak VRAM usage


def load_sr_model(model_path: str = MODEL_PATH) -> spandrel.ModelDescriptor:
    print(f"[SR] Loading model {model_path}", flush=True)
    model = spandrel.ModelLoader(device="cuda").load_from_file(model_path)
    model.eval()
    model.model.half()  # fp16 — ~3x faster on RTX
    with torch.inference_mode():
        dummy = torch.zeros(1, 3, 8, 8, device="cuda", dtype=torch.float16)
        model.model(dummy)
    print("[SR] Model ready (fp16)", flush=True)
    return model


def _upscale_batch(model: spandrel.ModelDescriptor, frames_bgr: list) -> list:
    """Upscale a list of BGR uint8 ndarray frames; return upscaled BGR uint8 list."""
    arr = np.stack(frames_bgr).astype(np.float32) / 255.0
    t = torch.from_numpy(arr).permute(0, 3, 1, 2).to("cuda").half()
    t = t[:, [2, 1, 0], :, :]  # BGR → RGB
    with torch.inference_mode():
        out = model.model(t)
    out = out[:, [2, 1, 0], :, :].clamp(0, 1)  # RGB → BGR
    out_np = (out.permute(0, 2, 3, 1).float().cpu().numpy() * 255).astype(np.uint8)
    del t, out
    torch.cuda.empty_cache()
    return [out_np[i] for i in range(out_np.shape[0])]


def upscale_file(
    model: spandrel.ModelDescriptor,
    input_path: str,
    output_path: str,
    target_w: int = 1080,
    target_h: int = 1920,
    batch_size: int = BATCH_SIZE,
    preview_seconds: Optional[float] = None,
    progress_cb: Optional[Callable[[int], None]] = None,
) -> None:
    """
    Upscale video at input_path with ESRGAN x4, pad to target_w×target_h,
    encode with NVENC, copy audio → output_path.

    preview_seconds: if set, only process the first N seconds (for preview mode).
    progress_cb: optional callable(pct: int) called periodically with 0-100.
    """
    cap = cv2.VideoCapture(input_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if preview_seconds is not None and preview_seconds > 0:
        max_frames = int(preview_seconds * fps)
        total = min(total, max_frames)
    else:
        max_frames = None

    # Read first frame to determine SR output size
    ret, first = cap.read()
    if not ret:
        cap.release()
        raise RuntimeError(f"[SR] Cannot read {input_path}")
    in_h, in_w = first.shape[:2]
    [sr_first] = _upscale_batch(model, [first])
    sr_h, sr_w = sr_first.shape[:2]
    print(f"[SR] {in_w}x{in_h} → {sr_w}x{sr_h}, fps={fps:.1f}, ~{total} frames", flush=True)

    vf = (
        f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease:flags=lanczos,"
        f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2"
    )

    # For preview mode: trim audio to match preview duration
    audio_args = []
    if max_frames is not None:
        preview_dur = max_frames / fps
        audio_args = ["-t", f"{preview_dur:.3f}"]

    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-pix_fmt", "bgr24", "-s", f"{sr_w}x{sr_h}",
        "-r", str(fps), "-i", "pipe:0",
        "-i", input_path,
        "-vf", vf,
        "-map", "0:v", "-map", "1:a?",
        *audio_args,
        "-c:v", "h264_nvenc", "-b:v", "10M",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-shortest",
        output_path,
    ]
    proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    proc.stdin.write(sr_first.tobytes())
    frame_idx = 1
    buf = []

    while True:
        if max_frames is not None and frame_idx >= max_frames:
            break
        ret, frame = cap.read()
        if not ret:
            break
        buf.append(frame)
        if len(buf) >= batch_size:
            for sr in _upscale_batch(model, buf):
                proc.stdin.write(sr.tobytes())
            frame_idx += len(buf)
            buf.clear()
            if progress_cb and total > 0:
                pct = min(99, int(frame_idx / total * 100))
                progress_cb(pct)
            elif frame_idx % 200 == 0:
                pct = int(frame_idx / total * 100) if total > 0 else 0
                print(f"[SR] {frame_idx}/{total} ({pct}%)", flush=True)

    if buf:
        for sr in _upscale_batch(model, buf):
            proc.stdin.write(sr.tobytes())
        frame_idx += len(buf)

    cap.release()
    proc.stdin.close()
    rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"[SR] ffmpeg encode failed (rc={rc})")
    if progress_cb:
        progress_cb(100)
    print(f"[SR] Done → {output_path} ({frame_idx} frames)", flush=True)


# ── Standalone entry point ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--target-w", type=int, default=1080)
    parser.add_argument("--target-h", type=int, default=1920)
    parser.add_argument("--batch", type=int, default=BATCH_SIZE)
    parser.add_argument("--model", default=MODEL_PATH)
    args = parser.parse_args()

    model = load_sr_model(args.model)
    upscale_file(model, args.input, args.output,
                 target_w=args.target_w, target_h=args.target_h,
                 batch_size=args.batch)


if __name__ == "__main__":
    main()
