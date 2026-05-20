"""
Lip Sync Service - 嵌入 gpu_service.py 的唇型同步模块

调用方式 (HTTP API):
  POST /lipsync
  Body: {"video_path": "...", "audio_path": "...", "output_path": "..."}

依赖:
  pip install insightface onnxruntime-gpu opencv-python numpy

模型文件位置: C:/Users/neo/lipsync/models/
  - wav2lip_gan.onnx  (Wav2Lip GAN ONNX export)
  - s3fd.onnx         (Face detection)
"""
import os
import logging
import subprocess
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)

LIPSYNC_DIR = Path("C:/Users/neo/lipsync")
MODELS_DIR = LIPSYNC_DIR / "models"
ENABLED = MODELS_DIR.exists() and (MODELS_DIR / "wav2lip_gan.onnx").exists()


def is_available() -> bool:
    """Check if lip sync models are deployed."""
    return ENABLED


async def run_lipsync(video_path: str, audio_path: str, output_path: str,
                      enhance_face: bool = True) -> bool:
    """
    Run lip sync: Wav2Lip ONNX inference.
    
    Args:
        video_path: Input video with face (mp4)
        audio_path: Target audio to sync lips to (wav/mp4)
        output_path: Output video path
        enhance_face: If True, apply GFPGAN to restore face quality
    
    Returns:
        True on success
    """
    import asyncio
    
    if not is_available():
        logger.warning("Lip sync not available (models not deployed)")
        return False
    
    script_path = LIPSYNC_DIR / "lipsync_infer.py"
    if not script_path.exists():
        logger.error(f"Inference script not found: {script_path}")
        return False
    
    cmd = [
        "python", str(script_path),
        "--video", video_path,
        "--audio", audio_path,
        "--output", output_path,
    ]
    if not enhance_face:
        cmd.append("--no-enhance")
    
    logger.info(f"[LipSync] Starting: {os.path.basename(video_path)} + {os.path.basename(audio_path)}")
    start = time.time()
    
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(LIPSYNC_DIR),
    )
    stdout, stderr = await proc.communicate()
    
    elapsed = time.time() - start
    
    if proc.returncode == 0 and os.path.exists(output_path):
        logger.info(f"[LipSync] Success in {elapsed:.1f}s: {output_path}")
        return True
    else:
        logger.error(f"[LipSync] Failed (code={proc.returncode}, {elapsed:.1f}s): {stderr.decode()[-300:]}")
        return False
