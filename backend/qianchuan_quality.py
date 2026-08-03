"""千川投流版质量检测。

用 ffprobe/ffmpeg 做轻量本地检查：音轨、非静音、分辨率、时长、解码错误风险、编码格式。
"""
from __future__ import annotations

import asyncio
import json
import os
import re

from gpu_execution import reject_local_media, require_remote_gpu
from typing import Dict, List, Optional


async def _run(*args: str, timeout: int = 60) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return 124, "", "timeout"
    return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")


async def ffprobe_json(path: str) -> Dict:
    reject_local_media("local ffprobe quality check")
    code, out, err = await _run(
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path, timeout=30
    )
    if code != 0:
        raise RuntimeError(f"ffprobe failed: {err[-300:]}")
    return json.loads(out or "{}")


async def volumedetect(path: str) -> Dict:
    reject_local_media("local audio quality check")
    code, _out, err = await _run(
        "ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af", "volumedetect", "-f", "null", "-", timeout=90
    )
    mean = re.search(r"mean_volume:\s*([-0-9.]+) dB", err)
    maxv = re.search(r"max_volume:\s*([-0-9.]+) dB", err)
    return {
        "ok": code == 0,
        "mean_volume_db": float(mean.group(1)) if mean else None,
        "max_volume_db": float(maxv.group(1)) if maxv else None,
        "raw_tail": err[-500:],
    }


async def decode_smoke(path: str) -> Dict:
    reject_local_media("local decode quality check")
    code, _out, err = await _run(
        "ffmpeg", "-v", "error", "-i", path, "-f", "null", "-", timeout=120
    )
    return {"ok": code == 0 and not err.strip(), "returncode": code, "errors": err[-1000:]}


async def check_qianchuan_video_quality(path: str, min_duration: float = 18.0, max_duration: float = 35.5) -> Dict:
    """Return a pending marker; the GPU service owns all media inspection."""
    require_remote_gpu("remote quality check")
    if not path:
        return {"path": path, "ok": False, "status": "waiting_for_remote_quality_report", "errors": ["GPU quality report required"], "warnings": []}
    return {"path": path, "ok": False, "status": "waiting_for_remote_quality_report", "errors": ["GPU quality report required"], "warnings": []}
