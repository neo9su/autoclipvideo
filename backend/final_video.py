"""Final publish-video post-processing.

统一成片出口的最后一道工序：
- 竖屏 4K 画布：2160x3840
- 输出帧率：50fps
- 非 9:16 画面使用模糊背景补齐，主体等比居中
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

from gpu_execution import reject_local_media


FINAL_VIDEO_WIDTH = 2160
FINAL_VIDEO_HEIGHT = 3840
FINAL_VIDEO_FPS = 50


async def postprocess_final_video(
    video_path: str,
    *,
    width: int = FINAL_VIDEO_WIDTH,
    height: int = FINAL_VIDEO_HEIGHT,
    fps: int = FINAL_VIDEO_FPS,
) -> Optional[str]:
    """Remote GPU postprocess boundary; local ffmpeg is forbidden."""
    reject_local_media("local final-video postprocess")

    src = Path(video_path)
    if not src.exists() or src.stat().st_size <= 0:
        logger.warning("Final postprocess skipped: missing video %s", video_path)
        return None

    if src.stem.endswith(f"_{width}x{height}_{fps}fps"):
        return str(src)

    out = src.with_name(f"{src.stem}_{width}x{height}_{fps}fps.mp4")
    tmp = src.with_name(f".{src.stem}_{width}x{height}_{fps}fps.tmp.mp4")

    vf = (
        f"[0:v]split=2[fgsrc][bgsrc];"
        f"[bgsrc]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},gblur=sigma=48:steps=2,"
        f"eq=brightness=-0.035:saturation=1.12[bg];"
        f"[fgsrc]scale={width}:{height}:force_original_aspect_ratio=decrease[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2,"
        f"fps={fps},format=yuv420p[v]"
    )
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-filter_complex", vf,
        "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-profile:v", "high", "-level", "5.2",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
        "-movflags", "+faststart",
        str(tmp),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0 or not tmp.exists() or tmp.stat().st_size <= 0:
        err = stderr.decode(errors="replace")[-500:] if stderr else ""
        logger.warning("Final postprocess failed for %s: %s", video_path, err)
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return None

    try:
        if out.exists():
            out.unlink()
        tmp.rename(out)
    except Exception as e:
        logger.warning("Final postprocess rename failed for %s: %s", video_path, e)
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return None

    try:
        src.unlink(missing_ok=True)
    except Exception as e:
        logger.debug("Unable to remove pre-postprocess source %s: %s", src, e)

    logger.info(
        "Final postprocess complete: %s → %s (%sx%s %sfps)",
        src.name, out.name, width, height, fps,
    )
    return str(out)
