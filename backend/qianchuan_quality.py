"""千川投流版质量检测。

用 ffprobe/ffmpeg 做轻量本地检查：音轨、非静音、分辨率、时长、解码错误风险、编码格式。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
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
    code, out, err = await _run(
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path, timeout=30
    )
    if code != 0:
        raise RuntimeError(f"ffprobe failed: {err[-300:]}")
    return json.loads(out or "{}")


async def volumedetect(path: str) -> Dict:
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
    code, _out, err = await _run(
        "ffmpeg", "-v", "error", "-i", path, "-f", "null", "-", timeout=120
    )
    return {"ok": code == 0 and not err.strip(), "returncode": code, "errors": err[-1000:]}


async def check_qianchuan_video_quality(path: str, min_duration: float = 18.0, max_duration: float = 35.5) -> Dict:
    report: Dict = {"path": path, "ok": False, "errors": [], "warnings": []}
    if not path or not os.path.exists(path):
        report["errors"].append("output file missing")
        return report

    try:
        probe = await ffprobe_json(path)
    except Exception as exc:
        report["errors"].append(str(exc))
        return report

    streams: List[Dict] = probe.get("streams") or []
    fmt = probe.get("format") or {}
    videos = [s for s in streams if s.get("codec_type") == "video"]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    if not videos:
        report["errors"].append("no video stream")
    if not audios:
        report["errors"].append("no audio stream")

    duration = float(fmt.get("duration") or videos[0].get("duration") or 0) if videos else 0.0
    report["duration"] = duration
    if duration < min_duration or duration > max_duration:
        report["errors"].append(f"duration {duration:.2f}s outside {min_duration:.0f}-{max_duration:.0f}s")

    if videos:
        v = videos[0]
        width, height = int(v.get("width") or 0), int(v.get("height") or 0)
        report.update({"width": width, "height": height, "video_codec": v.get("codec_name"), "pix_fmt": v.get("pix_fmt")})
        if (width, height) not in {(1080, 1920), (1440, 2560)}:
            report["errors"].append(f"resolution {width}x{height} is not 1080x1920 or 1440x2560")
        if v.get("codec_name") != "h264":
            report["errors"].append(f"video codec {v.get('codec_name')} is not h264")
        fps_expr = v.get("avg_frame_rate") or "0/1"
        try:
            num, den = fps_expr.split("/")
            fps = float(num) / max(1.0, float(den))
        except Exception:
            fps = 0.0
        report["fps"] = round(fps, 3)
        if abs(fps - 30.0) > 1.0:
            report["warnings"].append(f"fps {fps:.2f} is not near 30")

    if audios:
        a = audios[0]
        report.update({"audio_codec": a.get("codec_name"), "sample_rate": a.get("sample_rate")})
        if a.get("codec_name") != "aac":
            report["errors"].append(f"audio codec {a.get('codec_name')} is not aac")
        vol = await volumedetect(path)
        report["volume"] = vol
        if not vol.get("ok"):
            report["errors"].append("volumedetect failed")
        elif vol.get("max_volume_db") is None or vol.get("max_volume_db") < -45:
            report["errors"].append("audio appears silent")

    dec = await decode_smoke(path)
    report["decode"] = dec
    if not dec["ok"]:
        report["errors"].append("decode smoke test failed")

    report["ok"] = not report["errors"]
    return report
