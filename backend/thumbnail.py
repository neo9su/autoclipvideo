import asyncio
import os
from typing import Optional


async def _get_duration(mp4_path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
        mp4_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    stdout, _ = await proc.communicate()
    try:
        return float(stdout.strip())
    except (ValueError, TypeError):
        return 10.0


def _find_font() -> str:
    candidates = [
        # macOS
        "/System/Library/Fonts/PingFang.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        # Linux
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return ""


async def generate_thumbnail(mp4_path: str, offset: Optional[float] = None) -> Optional[str]:
    """Extract a styled thumbnail frame with text overlay. Falls back to plain frame on error."""
    out = mp4_path.replace(".mp4", "_thumb.jpg")

    duration = await _get_duration(mp4_path)
    seek = offset if offset is not None else max(1.0, duration * 0.3)

    font = _find_font()
    if font:
        filter_str = (
            "eq=brightness=0.05:saturation=1.3,"
            "drawbox=x=0:y=ih-160:w=iw:h=160:color=black@0.65:t=fill,"
            f"drawtext=fontfile='{font}':text='假发变美瞬间':fontcolor=white:fontsize=60"
            ":x=(w-text_w)/2:y=h-140:shadowx=2:shadowy=2,"
            f"drawtext=fontfile='{font}':text='点击查看同款':fontcolor=0xFFD700:fontsize=38"
            ":x=(w-text_w)/2:y=h-72"
        )
        cmd = [
            "ffmpeg", "-y", "-ss", f"{seek:.3f}", "-i", mp4_path,
            "-frames:v", "1", "-vf", filter_str, "-q:v", "3", out,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        if proc.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0:
            return out
        # Log and fall through to plain fallback
        import logging
        logging.getLogger(__name__).warning(
            f"Thumbnail drawtext failed, falling back: {stderr.decode()[-200:]}"
        )

    # Plain frame fallback
    cmd = ["ffmpeg", "-y", "-ss", f"{seek:.3f}", "-i", mp4_path,
           "-frames:v", "1", "-q:v", "3", out]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    await proc.communicate()
    return out if os.path.exists(out) else None
