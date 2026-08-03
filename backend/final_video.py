"""Remote-only final-video boundary."""
from __future__ import annotations

from typing import Optional

from gpu_execution import reject_local_media


async def postprocess_final_video(
    video_path: str,
    *,
    width: int = 2160,
    height: int = 3840,
    fps: int = 50,
) -> Optional[str]:
    """Reject local post-processing; the GPU service owns the final render."""
    reject_local_media(f"final video postprocess for {video_path}")
    return None
