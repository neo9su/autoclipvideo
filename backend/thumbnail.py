import asyncio
import os
from typing import Optional


async def generate_thumbnail(mp4_path: str, offset: float = 1.0) -> Optional[str]:
    """Use ffmpeg to extract a frame from mp4, return jpg path or None on failure."""
    out = mp4_path.replace(".mp4", "_thumb.jpg")
    cmd = ["ffmpeg", "-y", "-ss", str(offset), "-i", mp4_path,
           "-frames:v", "1", "-q:v", "3", out]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.communicate()
    return out if os.path.exists(out) else None
