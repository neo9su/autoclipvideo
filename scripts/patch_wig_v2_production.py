"""Stage/apply/rollback the production wig-v2 control and GPU patch."""
from __future__ import annotations

import argparse
import hashlib
import json
import py_compile
import re
import shutil
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(text: str, before: str, after: str, label: str) -> str:
    count = text.count(before)
    if count != 1:
        raise RuntimeError(f"anchor {label} count={count}")
    return text.replace(before, after, 1)


def stage(root: Path, release: Path, wig_module: Path) -> dict:
    before = json.loads((release / "manifest-before.json").read_text(encoding="utf-8"))
    backend = root / "backend"
    gpu = root / "gpu_service" / "main.py"
    sources = [backend / "qianchuan_script.py", backend / "qianchuan_video.py", gpu]
    for source in sources:
        expected = before["files"][str(source)]["sha256"]
        if digest(source) != expected:
            raise RuntimeError(f"source drift: {source}")

    after = release / "after"
    (after / "backend").mkdir(parents=True, exist_ok=True)
    (after / "gpu_service").mkdir(parents=True, exist_ok=True)
    shutil.copy2(wig_module, after / "backend" / "wig_preprocess.py")

    source = backend / "qianchuan_script.py"
    text = source.read_text(encoding="utf-8-sig")
    text = replace_once(
        text,
        "from typing import Dict, List, Optional\n",
        "from typing import Dict, List, Optional\n\nfrom wig_preprocess import retention_hook_plan\n",
        "script import",
    )
    text = replace_once(
        text,
        '        "selling_points": merged_points,\n',
        '        "selling_points": merged_points,\n        "retention_hooks": retention_hook_plan(duration),\n',
        "script hooks",
    )
    (after / "backend" / source.name).write_text(text, encoding="utf-8")

    source = backend / "qianchuan_video.py"
    text = source.read_text(encoding="utf-8-sig")
    text = replace_once(
        text,
        "from video_editing_skills import ensure_sfx_asset\n",
        "from video_editing_skills import ensure_sfx_asset\nfrom wig_preprocess import qianchuan_output_spec\n",
        "video import",
    )
    pattern = r'        config\["qianchuan_output_spec"\] = \{[^\n]*\}'
    if len(re.findall(pattern, text)) != 1:
        raise RuntimeError("video output spec anchor")
    text = re.sub(
        pattern,
        '        config["qianchuan_output_spec"] = {"vcodec": "h264", "acodec": "aac", **qianchuan_output_spec("vertical")}',
        text,
        count=1,
    )
    (after / "backend" / source.name).write_text(text, encoding="utf-8")

    text = gpu.read_text(encoding="utf-8-sig")
    text = replace_once(
        text,
        "    total_tts_duration: float = 0.0  # 总 TTS 时长，用于 -t 精确控制输出时长（替代 -shortest）\n",
        "    total_tts_duration: float = 0.0  # 总 TTS 时长，用于 -t 精确控制输出时长（替代 -shortest）\n    qianchuan_output_spec: dict = {}\n",
        "gpu request field",
    )
    text = replace_once(
        text,
        "async def _do_director_job(job_id: str, clips: list, ass_content: str,\n                            tts_audio_b64: str, transition_type: str,\n                            transition_duration: float, thumb_seek: float,\n                            total_tts_duration: float = 0.0):\n",
        "async def _do_director_job(job_id: str, clips: list, ass_content: str,\n                            tts_audio_b64: str, transition_type: str,\n                            transition_duration: float, thumb_seek: float,\n                            total_tts_duration: float = 0.0,\n                            qianchuan_output_spec: dict = None):\n",
        "gpu worker signature",
    )
    validation = '''        _update_director_job(job_id, status="processing", phase="preprocess", pct=0)
        output_spec = qianchuan_output_spec or {}
        resolution = str(output_spec.get("resolution") or "1080x1920")
        if resolution not in {"1080x1920", "1440x2560"}:
            raise ValueError(f"unsupported director resolution: {resolution}")
        output_w, output_h = (int(value) for value in resolution.split("x"))
        output_fps = int(output_spec.get("fps") or 25)
        if output_fps not in {25, 30}:
            raise ValueError(f"unsupported director fps: {output_fps}")
        output_bitrate = str(output_spec.get("video_bitrate") or "10M")
        if not re.fullmatch(r"[1-9][0-9]?[Mm]", output_bitrate):
            raise ValueError("invalid director video bitrate")
'''
    text = replace_once(
        text,
        '        _update_director_job(job_id, status="processing", phase="preprocess", pct=0)\n',
        validation,
        "gpu output validation",
    )
    text = replace_once(
        text,
        "video_filter = f\"[0:v]ass=filename='{escaped}':fontsdir='{fonts_esc}',format=yuv420p[vout]\"",
        "video_filter = f\"[0:v]scale={output_w}:{output_h}:flags=lanczos,fps={output_fps},ass=filename='{escaped}':fontsdir='{fonts_esc}',format=yuv420p[vout]\"",
        "gpu subtitle scale fonts",
    )
    text = replace_once(
        text,
        "            else:\n                video_filter = f\"[0:v]ass=filename='{escaped}',format=yuv420p[vout]\"\n            if audio_filter:\n",
        "            else:\n                video_filter = f\"[0:v]scale={output_w}:{output_h}:flags=lanczos,fps={output_fps},ass=filename='{escaped}',format=yuv420p[vout]\"\n            if audio_filter:\n",
        "gpu subtitle scale",
    )
    text = replace_once(
        text,
        '        rc = await _run_ffmpeg(\n            *ff_args,\n            "-c:v", "h264_nvenc", "-b:v", "10M",',
        '        rc = await _run_ffmpeg(\n            *ff_args,\n            "-c:v", "h264_nvenc", "-b:v", output_bitrate,',
        "gpu final bitrate",
    )
    text = replace_once(
        text,
        "async def _run_director_job(job_id: str, clips: list, ass_content: str,\n                             tts_audio_b64: str, transition_type: str,\n                             transition_duration: float, thumb_seek: float,\n                             total_tts_duration: float = 0.0):\n",
        "async def _run_director_job(job_id: str, clips: list, ass_content: str,\n                             tts_audio_b64: str, transition_type: str,\n                             transition_duration: float, thumb_seek: float,\n                             total_tts_duration: float = 0.0,\n                             qianchuan_output_spec: dict = None):\n",
        "gpu runner signature",
    )
    text = replace_once(
        text,
        "                    transition_type, transition_duration, thumb_seek, total_tts_duration),\n",
        "                    transition_type, transition_duration, thumb_seek, total_tts_duration, qianchuan_output_spec),\n",
        "gpu runner pass",
    )
    text = replace_once(
        text,
        "        req.total_tts_duration,\n    ))\n",
        "        req.total_tts_duration,\n        req.qianchuan_output_spec,\n    ))\n",
        "gpu endpoint pass",
    )
    (after / "gpu_service" / "main.py").write_text(text, encoding="utf-8")

    staged = [
        after / "backend" / "wig_preprocess.py",
        after / "backend" / "qianchuan_script.py",
        after / "backend" / "qianchuan_video.py",
        after / "gpu_service" / "main.py",
    ]
    for path in staged:
        py_compile.compile(str(path), doraise=True)
    result = {"staged": [str(path) for path in staged],
              "sha256": {str(path): digest(path) for path in staged}}
    (release / "manifest-after.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def transition(root: Path, release: Path, rollback: bool = False) -> dict:
    backend = root / "backend"
    targets = {
        backend / "wig_preprocess.py": release / "after" / "backend" / "wig_preprocess.py",
        backend / "qianchuan_script.py": release / "after" / "backend" / "qianchuan_script.py",
        backend / "qianchuan_video.py": release / "after" / "backend" / "qianchuan_video.py",
        root / "gpu_service" / "main.py": release / "after" / "gpu_service" / "main.py",
    }
    before = json.loads((release / "manifest-before.json").read_text(encoding="utf-8"))
    if rollback:
        targets = {
            target: Path(before["files"][str(target)]["backup"])
            for target in targets if str(target) in before["files"]
        } | {backend / "wig_preprocess.py": None}
    else:
        for target in targets:
            if target.exists() and str(target) in before["files"]:
                if digest(target) != before["files"][str(target)]["sha256"]:
                    raise RuntimeError(f"source drift before apply: {target}")
    if rollback:
        after_manifest = json.loads((release / "manifest-after.json").read_text(encoding="utf-8"))
        for target in targets:
            if target.exists() and target.name != "wig_preprocess.py":
                staged = release / "after" / ("gpu_service" if target.name == "main.py" else "backend") / target.name
                if digest(target) != after_manifest["sha256"][str(staged)]:
                    raise RuntimeError(f"source drift before rollback: {target}")
    for target, source in targets.items():
        if source is None:
            target.unlink(missing_ok=True)
        else:
            shutil.copy2(source, target)
    return {"mode": "rollback" if rollback else "apply", "changed": [str(p) for p in targets]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("stage", "apply", "rollback"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--wig-module", type=Path)
    args = parser.parse_args()
    if args.mode == "stage":
        if not args.wig_module:
            parser.error("--wig-module is required for stage")
        result = stage(args.root, args.release, args.wig_module)
    else:
        result = transition(args.root, args.release, rollback=args.mode == "rollback")
    print(json.dumps(result, ensure_ascii=False))
