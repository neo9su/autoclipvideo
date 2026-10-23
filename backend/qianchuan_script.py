"""千川投流版脚本生成。

独立于 classic/director/creative 的固定广告结构：
0-3s 结果钩子；3-7s 痛点；7-13s 产品证据；13-19s 上脸/使用效果；19-23s CTA。
默认 22s，可配置 18-25s（硬上限 35s）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from wig_preprocess import retention_hook_plan


DEFAULT_DURATION = 22.0
MIN_DURATION = 18.0
MAX_RECOMMENDED_DURATION = 25.0
HARD_MAX_DURATION = 35.0


@dataclass(frozen=True)
class QianchuanSceneTemplate:
    scene_id: int
    scene_type: str
    title: str
    start_ratio: float
    end_ratio: float
    visual_keywords: List[str]


# Ratios are based on the requested 0-3/3-7/7-13/13-19/19-23 structure.
SCENE_TEMPLATES: List[QianchuanSceneTemplate] = [
    QianchuanSceneTemplate(1, "result_hook", "结果钩子", 0 / 23, 3 / 23, ["最终效果", "正脸", "显白", "发缝自然", "快速吸睛"]),
    QianchuanSceneTemplate(2, "pain_point", "痛点", 3 / 23, 7 / 23, ["痛点", "低头少", "手不要遮脸", "发网", "发际线"]),
    QianchuanSceneTemplate(3, "product_proof", "产品证据", 7 / 23, 13 / 23, ["发缝近景", "头顶近景", "发丝特写", "颜色特写", "材质证据"]),
    QianchuanSceneTemplate(4, "tryon_result", "上脸/使用效果", 13 / 23, 19 / 23, ["上脸效果", "侧脸", "背面", "全身", "稳定测试", "甩头", "梳理"]),
    QianchuanSceneTemplate(5, "cta", "CTA", 19 / 23, 23 / 23, ["小黄车", "下单", "同款", "购买引导", "主播正脸"]),
]


KEY_SELLING_POINTS = ["不用戴发网", "免发网", "显白", "发缝自然", "稳固", "小黄车"]


def clamp_duration(duration: Optional[float]) -> float:
    """Clamp target duration. API accepts <=35s but defaults/recommends 18-25s."""
    if duration is None:
        return DEFAULT_DURATION
    try:
        value = float(duration)
    except Exception:
        return DEFAULT_DURATION
    if value <= 0:
        return DEFAULT_DURATION
    return max(MIN_DURATION, min(HARD_MAX_DURATION, value))


def _compact_product_name(group_data: Dict, product_context: Optional[Dict]) -> str:
    product_name = (product_context or {}).get("product_name") or ""
    label = group_data.get("label") or ""
    model = group_data.get("wig_model") or ""
    color = group_data.get("wig_color") or ""
    parts = [p for p in [product_name, color, model, label] if p]
    if not parts:
        return "这款假发"
    text = " ".join(dict.fromkeys(parts))
    return text[:36]


def generate_qianchuan_script(
    group_data: Dict,
    product_context: Optional[Dict] = None,
    target_duration: Optional[float] = None,
    selling_points: Optional[List[str]] = None,
) -> Dict:
    """Build a deterministic Qianchuan ad script in five conversion scenes."""
    duration = clamp_duration(target_duration)
    points = [p for p in (selling_points or []) if p]
    if not points:
        points = []
    # Caller keywords remain retrieval metadata, not proof for spoken claims.
    merged_points = list(dict.fromkeys(points))[:8]
    product_name = _compact_product_name(group_data, product_context)
    color = (group_data.get("wig_color") or (product_context or {}).get("matched_color") or "").strip()
    model = (group_data.get("wig_model") or "").strip()

    scene_text = {
        "result_hook": f"先看{color or model or '这款假发'}的上脸效果，再看近景细节。",
        "pain_point": "选假发先看哪里？先看整体轮廓，再看刘海和发尾。",
        "product_proof": "近看头顶、发丝和发尾，具体细节放大给你看。",
        "tryon_result": "正脸、侧脸换个角度看，再对照整体轮廓和发尾。",
        "cta": "喜欢这个发型，先收藏，再对照细节选适合自己的款。",
    }

    scenes: List[Dict] = []
    for tmpl in SCENE_TEMPLATES:
        start = round(duration * tmpl.start_ratio, 2)
        end = round(duration * tmpl.end_ratio, 2)
        scenes.append({
            "scene_id": tmpl.scene_id,
            "scene_type": tmpl.scene_type,
            "title": tmpl.title,
            "timestamp_start": start,
            "timestamp_end": end,
            "duration": round(end - start, 2),
            "voiceover_text": scene_text[tmpl.scene_type],
            "visual_requirements": tmpl.visual_keywords,
            "priority_shots": tmpl.visual_keywords,
            "subtitle_keywords": [kw for kw in merged_points if kw in scene_text[tmpl.scene_type]],
        })

    return {
        "mode": "qianchuan",
        "version": "1.1",
        "target_duration": duration,
        "structure": "0-3s结果钩子 / 3-7s痛点 / 7-13s产品证据 / 13-19s上脸效果 / 19-23s CTA",
        "product_context": product_context or {},
        "selling_points": merged_points,
        "selling_points_source": "caller_supplied_unverified" if points else "none",
        "retention_hooks": retention_hook_plan(duration),
        "generated_at": time.time(),
        "scenes": scenes,
    }
