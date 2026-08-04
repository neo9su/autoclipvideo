"""Remote GPU-only final publish-video post-processing."""

from typing import Optional

from gpu_execution import reject_local_media


async def postprocess_final_video(
    video_path: str,
    *,
    width: int = 2160,
    height: int = 3840,
    fps: int = 50,
) -> Optional[str]:
    """Reject local post-processing; the GPU service owns ffmpeg execution."""
    del video_path, width, height, fps
    reject_local_media("final video postprocess")
    return None
