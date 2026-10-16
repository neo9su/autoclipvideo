"""Pure policies for wig-safe preprocessing, naming and retention planning.

The functions in this module do not run models or edit media.  They turn
reviewed transcript/visual evidence into deterministic render constraints.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, Iterable, List, Mapping, Optional


POLICY_VERSION = "wig-preprocess-v2"
FEATURE_PATTERNS = (
    ("齐刘海", ("齐刘海",)),
    ("长发", ("长发", "长卷发", "长直发", "长款", "及腰", "过肩")),
    ("短发", ("短发", "短款", "波波头", "锁骨发")),
    ("卷发", ("卷发", "卷度", "大波浪", "羊毛卷", "微卷")),
    ("直发", ("直发", "长直", "顺直")),
    ("免发网", ("免发网", "不用戴发网", "无需发网")),
    ("仿递针", ("仿递针", "递针工艺", "仿真递针")),
)
_ALIAS_SPLIT = re.compile(r"[&＆/／|｜、,，;；]+")
_BAD_FILENAME = re.compile(r"[\\/:*?\"<>|\x00-\x1f]+")


def normalize(value: object) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or "")).casefold())


def product_aliases(product: Mapping[str, object]) -> List[str]:
    """Return explicit aliases plus useful components of compound product names."""
    name = str(product.get("product_name") or product.get("name") or "").strip()
    values = [name, *(product.get("aliases") or [])]
    if name:
        values.extend(part.strip() for part in _ALIAS_SPLIT.split(name))
    aliases = [normalize(value) for value in values if len(normalize(value)) >= 2]
    return list(dict.fromkeys(aliases))


def resolve_spoken_product(text: str, products: Iterable[Mapping[str, object]]) -> Dict:
    """Resolve transcript mentions without guessing when aliases collide."""
    source = normalize(text)
    hits: Dict[str, List[str]] = {}
    rows: Dict[str, Mapping[str, object]] = {}
    for product in products:
        key = str(product.get("key") or product.get("id") or product.get("product_id") or "").strip()
        if not key:
            continue
        matched = [alias for alias in product_aliases(product) if alias in source]
        if matched:
            hits[key] = matched
            rows[key] = product
    if len(hits) != 1:
        return {"ok": False, "product_key": None, "product": None, "hits": hits,
                "reason": "no_product_mention" if not hits else "ambiguous_product_mention"}
    key = next(iter(hits))
    return {"ok": True, "product_key": key, "product": dict(rows[key]),
            "hits": hits[key], "reason": "single_catalog_product"}


def extract_features(*texts: object) -> List[str]:
    source = normalize(" ".join(str(text or "") for text in texts))
    return [label for label, aliases in FEATURE_PATTERNS
            if any(normalize(alias) in source for alias in aliases)]


def build_asset_name(product_name: str, color: Optional[str], features: Iterable[str], suffix: str = "") -> str:
    """Build 发型名称+颜色+特征 while keeping a filesystem-safe stable label."""
    parts = [str(product_name or "").strip(), str(color or "").strip()]
    parts.extend(str(feature).strip() for feature in features)
    clean = [_BAD_FILENAME.sub("", part).strip(" ._") for part in parts if part and part.strip()]
    label = "_".join(dict.fromkeys(part for part in clean if part)) or "未知发型"
    return label + suffix


def group_same_wig_segments(segments: Iterable[Mapping[str, object]]) -> Dict[str, List[Dict]]:
    """Group approved intervals by identity; unknown intervals never cross-mix."""
    grouped: Dict[str, List[Dict]] = {}
    for index, raw in enumerate(segments):
        segment = dict(raw)
        identity = str(segment.get("identity_key") or "").strip()
        if not identity:
            identity = f"unknown:{segment.get('recording_id', 'recording')}:{index}"
            segment["identity_unresolved"] = True
        grouped.setdefault(identity, []).append(segment)
    for items in grouped.values():
        items.sort(key=lambda item: (str(item.get("recording_id") or ""), float(item.get("start_sec") or 0)))
    return grouped


def retention_hook_plan(duration: float) -> List[Dict]:
    """Plan repeated open loops without duplicating the whole sales structure."""
    beats = (
        (0.0, "high_light", "第一帧进入上脸结果或动作高光"),
        (3.0, "open_loop", "补一个细节悬念或核心利益点"),
        (5.0, "proof_tease", "先给局部证据，详细解释后置"),
        (10.0, "new_information", "切换角度或动作，提供新信息"),
        (15.0, "rehook", "提出下一项真实卖点或异议"),
        (30.0, "rehook", "动态证据或场景重置后再收口"),
    )
    return [{"time": timepoint, "type": kind, "purpose": purpose}
            for timepoint, kind, purpose in beats if timepoint < float(duration)]


def qianchuan_output_spec(orientation: str = "vertical") -> Dict:
    if orientation == "horizontal":
        return {"aspect_ratio": "16:9", "resolution": "2560x1440", "fps": 30,
                "video_bitrate": "8M", "min_video_bitrate_kbps": 516,
                "max_size_mb": 1000, "duration_range_seconds": [4, 300]}
    return {"aspect_ratio": "9:16", "resolution": "1440x2560", "fps": 30,
            "video_bitrate": "8M", "min_video_bitrate_kbps": 516,
            "max_size_mb": 1000, "duration_range_seconds": [4, 300]}
