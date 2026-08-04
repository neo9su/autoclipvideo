"""Auditable hard gates for wig-category Qianchuan投流 materials.

This module validates metadata before a material can be marked投放-ready. It
contains no media processing and is intentionally independent from director mode.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional

AUDIENCES = ("产后妈妈群", "职场白领群", "中老年刚需群", "时尚变美群")
TEMPLATES = {
    "头皮/发际线微距": ("中老年刚需群", "产后妈妈群"),
    "佩戴全流程": ("产后妈妈群", "中老年刚需群"),
    "佩戴前后反差": ("职场白领群", "时尚变美群"),
    "真实用户开箱实测": ("产后妈妈群", "职场白领群", "中老年刚需群", "时尚变美群"),
}
REQUIRED_DEDUP_DIMENSIONS = {"光源", "服饰配饰", "画幅", "BGM", "字幕样式", "色调"}
REQUIRED_COPY_KEYS = ("A", "B", "C")
ROLE_ASSIGNMENTS = {
    "产品经理": "小贾",
    "千川投流专家": "小川",
    "短视频剪辑专家": "小映",
    "广告视觉专家": "Leo",
    "AI专家": "小智",
    "系统运维专家": "小维",
}


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return []


def build_qianchuan_metadata(
    *,
    target_audience: Optional[str] = None,
    excluded_audiences: Optional[Iterable[str]] = None,
    bid_coefficient: Optional[float] = None,
    template_type: Optional[str] = None,
    dedup_actions: Optional[Iterable[str]] = None,
    authenticity_check: Optional[Mapping[str, Any]] = None,
    copy_versions: Optional[Mapping[str, str]] = None,
    trust_proof: Optional[str] = None,
    stability_evidence: Optional[Iterable[str]] = None,
    ai_usage: Optional[Iterable[str]] = None,
    ai_generated_human_wig_scene: bool = False,
    execution_node: str = "remote-gpu",
) -> Dict[str, Any]:
    """Normalize user-supplied campaign metadata without inventing evidence."""
    return {
        "target_audience": target_audience,
        "excluded_audiences": [str(item) for item in (excluded_audiences or []) if str(item).strip()],
        "bid_coefficient": bid_coefficient,
        "template_type": template_type,
        "dedup_actions": [str(item) for item in (dedup_actions or []) if str(item).strip()],
        "authenticity_check": dict(authenticity_check or {}),
        "copy_versions": {str(k): str(v) for k, v in (copy_versions or {}).items()},
        "trust_proof": trust_proof,
        "stability_evidence": [str(item) for item in (stability_evidence or []) if str(item).strip()],
        "ai_usage": [str(item) for item in (ai_usage or []) if str(item).strip()],
        "ai_generated_human_wig_scene": bool(ai_generated_human_wig_scene),
        "execution_node": execution_node,
        "lifecycle_days": 11,
        "optimization_day": 7,
        "budget_test_split": {"cold_start": 1 / 3, "winner_scale": 0.7, "continued_test": 0.3},
        "role_assignments": dict(ROLE_ASSIGNMENTS),
    }


def validate_qianchuan_metadata(metadata: Mapping[str, Any]) -> Dict[str, Any]:
    """Return an auditable pass/fail report; missing evidence always fails."""
    errors: List[str] = []
    audience = metadata.get("target_audience")
    if audience not in AUDIENCES:
        errors.append("缺少或无效的主攻人群")
    if not _as_list(metadata.get("excluded_audiences")):
        errors.append("缺少排除人群")
    bid = metadata.get("bid_coefficient")
    if not isinstance(bid, (int, float)) or isinstance(bid, bool) or bid <= 0:
        errors.append("缺少有效出价系数")
    template = metadata.get("template_type")
    if template not in TEMPLATES:
        errors.append("缺少或无效的剪辑模板")
    dedup = set(_as_list(metadata.get("dedup_actions")))
    if len(dedup) < 3 or not dedup <= REQUIRED_DEDUP_DIMENSIONS:
        errors.append("去重动作至少需要 3 项有效维度")
    copies = metadata.get("copy_versions")
    if not isinstance(copies, Mapping) or any(not _non_empty(copies.get(key)) for key in REQUIRED_COPY_KEYS):
        errors.append("缺少 A/B/C 三版本文案")
    if not _non_empty(metadata.get("trust_proof")):
        errors.append("缺少信任证明")
    evidence = set(_as_list(metadata.get("stability_evidence")))
    if not evidence & {"摇头晃脑", "风吹"}:
        errors.append("缺少摇头晃脑或风吹动态稳定性证据")
    authenticity = metadata.get("authenticity_check")
    if not isinstance(authenticity, Mapping) or authenticity.get("passed") is not True:
        errors.append("缺少真实感检查")
    if metadata.get("ai_generated_human_wig_scene") is True:
        errors.append("禁止 AI 生成人物佩戴假发画面")
    if metadata.get("execution_node") != "remote-gpu":
        errors.append("执行节点必须为 remote-gpu")
    return {
        "eligible_for_delivery": not errors,
        "errors": errors,
        "checked_rules": ["target_audience", "excluded_audiences", "bid_coefficient", "template_type", "copy_versions", "trust_proof", "stability_evidence", "dedup_actions", "authenticity_check", "ai_generation_ban", "execution_node"],
        "audiences": list(AUDIENCES),
        "template_mapping": {key: list(value) for key, value in TEMPLATES.items()},
    }
