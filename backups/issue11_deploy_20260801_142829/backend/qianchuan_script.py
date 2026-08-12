"""千川投流版脚本生成。

独立于 classic/director/creative 的固定广告结构：
0-3s 结果钩子；3-7s 痛点；7-13s 产品证据；13-19s 上脸/使用效果；19-23s CTA。
默认 22s，可配置 18-25s（硬上限 35s）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List, Optional


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
    # Preserve product-specific keywords first, then defaults.
    merged_points = list(dict.fromkeys(points + KEY_SELLING_POINTS))[:8]
    product_name = _compact_product_name(group_data, product_context)
    color = (group_data.get("wig_color") or (product_context or {}).get("matched_color") or "").strip()
    model = (group_data.get("wig_model") or "").strip()

    scene_text = {
        "result_hook": f"戴上直接看效果，{color or product_name}真的很显白，发缝也很自然。",
        "pain_point": f"不想戴发网、怕勒头又怕假？这款重点就是省步骤，出门前快速整理。",
        "product_proof": f"近看发丝和头顶细节，{('、'.join(merged_points[:3]))}，颜色和卷度都要对版。",
        "tryon_result": f"正脸侧脸都看一下，梳理和轻甩也稳，日常通勤拍照都能撑住。",
        "cta": f"喜欢{model or color or '这款'}的姐妹，点小黄车看同款，先收藏再下单。",
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
            "subtitle_keywords": [kw for kw in merged_points if kw in scene_text[tmpl.scene_type]] or merged_points[:3],
        })

    return {
        "mode": "qianchuan",
        "version": "1.0",
        "target_duration": duration,
        "structure": "0-3s结果钩子 / 3-7s痛点 / 7-13s产品证据 / 13-19s上脸效果 / 19-23s CTA",
        "product_context": product_context or {},
        "selling_points": merged_points,
        "generated_at": time.time(),
        "scenes": scenes,
    }
