"""千川投流版质量检测。

通过远端 GPU 服务完成质量检查；控制面不执行本机 ffprobe/ffmpeg。
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


async def _remote_quality(job_id: str) -> Dict:
    """Ask the GPU worker to inspect its own output; never probe the download locally."""
    import aiohttp
    require_remote_gpu("remote media quality check")
    gpu_url = os.environ.get("GPU_SERVICE_URL", "http://10.190.0.203:8877").rstrip("/")
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
        async with session.get(f"{gpu_url}/director-jobs/{job_id}/quality") as response:
            if response.status != 200:
                raise RuntimeError(f"remote quality probe returned HTTP {response.status}")
            payload = await response.json()
    return payload


MIN_QUALITY_SCORE = 80.0
REQUIRED_REVIEW_FIELDS = ("timepoint", "subtitle", "shot", "selling_point", "audio_visual")


def _review_report(quality: Dict) -> Dict:
    """Normalize the remote 小美 report into auditable issue-level evidence."""
    raw_issues = quality.get("issues") or quality.get("review", {}).get("issues") or []
    issues = []
    for item in raw_issues:
        if isinstance(item, dict):
            issues.append({field: item.get(field, "未提供") for field in REQUIRED_REVIEW_FIELDS} | {
                "severity": item.get("severity", "warning"),
                "detail": item.get("detail", ""),
            })
        else:
            issues.append({"timepoint": "未提供", "subtitle": "未提供", "shot": "未提供",
                           "selling_point": "未提供", "audio_visual": "未提供",
                           "severity": "warning", "detail": str(item)})
    score = quality.get("score")
    try:
        score = float(score)
    except (TypeError, ValueError):
        score = None
    hard_gate_failures = list(quality.get("hard_gate_failures") or quality.get("gate_failures") or [])
    if score is None:
        hard_gate_failures.append("remote report missing score")
    elif score < MIN_QUALITY_SCORE:
        hard_gate_failures.append(f"score {score:.1f} below {MIN_QUALITY_SCORE:.0f}")
    return {
        "reviewer": "小美",
        "iteration": quality.get("iteration", 1),
        "score": score,
        "issues": issues,
        "hard_gate_failures": hard_gate_failures,
        "execution_node": quality.get("execution_node", "remote-gpu"),
        "job_id": quality.get("job_id"),
    }


def _apply_quality_gate(quality: Dict) -> Dict:
    review = _review_report(quality)
    quality = {**quality, "score": review["score"], "review": review,
               "hard_gate_failures": review["hard_gate_failures"],
               "ok": bool(quality.get("ok", True)) and not review["hard_gate_failures"]}
    return quality


async def check_qianchuan_video_quality(path: str, min_duration: float = 18.0, max_duration: float = 35.5, job_id: Optional[str] = None) -> Dict:
    if job_id:
        try:
            report = await _remote_quality(job_id)
            report["path"] = path
            report["execution_node"] = "remote-gpu"
            report["job_id"] = job_id
            return _apply_quality_gate(report)
        except Exception as exc:
            return {"path": path, "ok": False, "errors": [str(exc)], "warnings": [],
                    "execution_node": "remote-gpu", "job_id": job_id,
                    "hard_gate_failures": ["remote quality backend unavailable"]}
    return {"path": path, "ok": False, "errors": ["remote GPU job_id is required; local quality fallback is disabled"],
            "warnings": [], "execution_node": "remote-gpu",
            "hard_gate_failures": ["missing remote job_id"]}
