"""千川投流版视频合成包装层。

复用 DirectorVideoComposer 的 GPU/NVENC 路径，同时为每个 segment 补充 qianchuan edit_actions；
提供 GPU 服务消费的 ASS 高亮字幕和提示音元数据；本机不执行媒体处理。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

from director_video import DirectorVideoComposer
from video_editing_skills import ensure_sfx_asset

QIANCHUAN_KEYWORDS = [
    "不用戴发网", "免发网", "蜜茶橘棕", "羊毛卷", "显白", "发缝自然", "稳固", "小黄车",
]

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: QCMain,Arial,92,&H00FFFFFF,&H000000FF,&H90202020,&H60000000,1,0,0,0,100,100,1,0,1,4,1,2,72,72,260,1
Style: QCKW,Arial,118,&H0000CCFF,&H000000FF,&H90101010,&H60000000,1,0,0,0,100,100,0,0,1,6,3,9,72,72,150,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ensure_prompt_sfx(path: Optional[str] = None) -> str:
    """Return a remote asset identifier; never synthesize media on the control plane."""
    return path or "remote://qianchuan_click.wav"


def _sec_to_ass(s: float) -> str:
    s = max(0.0, float(s))
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    return f"{h}:{m:02d}:{sec:05.2f}"


def _highlight(text: str) -> str:
    escaped = (text or "").replace("{", "").replace("}", "")
    for kw in sorted(QIANCHUAN_KEYWORDS, key=len, reverse=True):
        if kw in escaped:
            escaped = escaped.replace(kw, r"{\c&H0000CCFF&\b1\bord6}" + kw + r"{\r}", 1)
    return escaped


def build_qianchuan_ass(script: Dict, audio_segments: Optional[List[Dict]] = None) -> str:
    """Build safe-zone ASS subtitles with keyword emphasis."""
    dur_by_scene = {}
    if audio_segments:
        dur_by_scene = {s.get("scene_id"): s.get("duration") for s in audio_segments if s.get("scene_id") is not None}
    events: List[str] = []
    cursor = 0.0
    for scene in script.get("scenes", []):
        sid = scene.get("scene_id")
        start = cursor if dur_by_scene else float(scene.get("timestamp_start") or 0)
        dur = float(dur_by_scene.get(sid) or scene.get("duration") or (float(scene.get("timestamp_end") or 0) - start) or 3.0)
        end = start + max(1.0, dur)
        text = _highlight(scene.get("voiceover_text") or scene.get("description") or "")
        anim = r"{\fad(80,80)\t(0,220,\fscx108\fscy108)\t(220,420,\fscx100\fscy100)}"
        events.append(f"Dialogue: 0,{_sec_to_ass(start)},{_sec_to_ass(end)},QCMain,,0,0,0,,{anim}{text}")
        # Pop only the first keyword in the upper-right safe area.
        for kw in QIANCHUAN_KEYWORDS:
            if kw in (scene.get("voiceover_text") or ""):
                pop_end = min(end, start + 1.2)
                events.append(f"Dialogue: 1,{_sec_to_ass(start + 0.15)},{_sec_to_ass(pop_end)},QCKW,,0,0,0,,{{\\an9\\fad(0,180)\\t(0,160,\\fscx125\\fscy125)}}{kw}")
                break
        cursor = end
    return ASS_HEADER + "\n".join(events) + "\n"


def build_sound_cues(script: Dict, audio_segments: Optional[List[Dict]] = None, sfx_path: Optional[str] = None) -> List[Dict]:
    """Return metadata for subtle keyword cues. GPU service may mix this WAV at given timestamps."""
    sfx = ensure_prompt_sfx(sfx_path)
    cues: List[Dict] = []
    cursor = 0.0
    dur_by_scene = {s.get("scene_id"): s.get("duration") for s in (audio_segments or []) if s.get("scene_id") is not None}
    for scene in script.get("scenes", []):
        start = cursor if dur_by_scene else float(scene.get("timestamp_start") or 0)
        text = scene.get("voiceover_text") or ""
        for kw in QIANCHUAN_KEYWORDS:
            if kw in text:
                cues.append({"time": round(start + 0.20, 2), "keyword": kw, "sfx_path": sfx, "gain_db": -12})
                break
        cursor = start + float(dur_by_scene.get(scene.get("scene_id")) or scene.get("duration") or 3.0)
    return cues


class QianchuanVideoComposer(DirectorVideoComposer):
    """Thin isolated composer that reuses proven director GPU path with qianchuan metadata."""

    async def compose_qianchuan_video(
        self,
        matched_segments: List[Dict],
        audio_path: str,
        script: Dict,
        audio_segments: Optional[List[Dict]] = None,
        config: Optional[Dict] = None,
    ) -> Optional[str]:
        config = dict(config or {})
        config.setdefault("video_style", "dynamic")
        config["mode"] = "qianchuan"
        config["qianchuan_ass_content"] = build_qianchuan_ass(script, audio_segments)
        config["qianchuan_sound_cues"] = build_sound_cues(script, audio_segments)
        config["qianchuan_output_spec"] = {"vcodec": "h264", "acodec": "aac", "resolution": "1080x1920", "fps": 30}

        enriched: List[Dict] = []
        for item in matched_segments:
            clone = dict(item)
            seg = dict(clone.get("script_segment") or {})
            seg.setdefault("mode", "qianchuan")
            seg.setdefault("edit_actions", clone.get("edit_actions") or [])
            clone["script_segment"] = seg
            if seg.get("scene_type") in {"detail", "product", "product_proof"}:
                actions = list(seg.get("edit_actions") or [])
                if not any(a.get("type") in {"detail_zoom", "pip_detail"} for a in actions if isinstance(a, dict)):
                    actions.append({"type": "pip_detail", "region": "upper_right", "intensity": 0.7})
                seg["edit_actions"] = actions
            clone.setdefault("edit_actions", seg["edit_actions"])
            enriched.append(clone)

        if not matched_segments and script.get("preview_mode"):
            raise RuntimeError("千川预览无法合成: 没有可用录像片段")
        return await self.compose_final_video(enriched, audio_path, config, tts_audio_segments=audio_segments)
