"""千川投流版商品与镜头强匹配。

低于阈值时调用方必须拒绝生成，避免错品/错色投流素材。
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, Iterable, List, Optional, Tuple

import aiosqlite

try:
    from director_matcher import SemanticMatcher
except Exception:  # pragma: no cover
    SemanticMatcher = None  # type: ignore


POSITIVE_SHOT_KEYWORDS = {
    "最终效果": 1.4, "正脸": 1.4, "上脸": 1.3, "发缝": 1.5, "头顶": 1.2,
    "近景": 1.0, "特写": 1.0, "发丝": 1.1, "卷度": 1.0, "颜色": 1.1,
    "侧脸": 0.8, "背面": 0.7, "全身": 0.7, "拉扯": 1.1, "甩头": 1.0,
    "梳理": 0.9, "稳固": 1.2, "小黄车": 0.8, "链接": 0.6,
}
NEGATIVE_SHOT_KEYWORDS = {
    "手遮": -1.2, "遮脸": -1.2, "低头": -0.8, "教程": -0.6, "直播间": -0.5,
    "杂乱": -0.8, "错色": -2.0, "不是这个颜色": -2.0, "别拍": -1.0,
}


def _tokens(*values: object) -> List[str]:
    out: List[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            out.extend(_tokens(*value))
            continue
        text = str(value).strip().lower()
        if not text:
            continue
        # Keep Chinese phrases, split common separators.
        for part in re.split(r"[\s,，;；/|、]+", text):
            part = part.strip().lower()
            if len(part) >= 2:
                out.append(part)
    return list(dict.fromkeys(out))


def _contains_score(haystack: str, needles: Iterable[str], weight: float) -> Tuple[float, List[str]]:
    needle_list = [n for n in needles if n]
    hits = [n for n in needle_list if n.lower() in haystack]
    return min(1.0, len(hits) / max(1, len(needle_list))) * weight, hits


async def load_group_context(db_path: str, group_id: int, product_id: Optional[str] = None) -> Dict:
    """Load group/product/SRT/director context for matching."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT cg.*, r.name AS room_name
               FROM clip_groups cg LEFT JOIN rooms r ON r.id = cg.room_id
               WHERE cg.id = ?""",
            (group_id,),
        ) as cur:
            group = await cur.fetchone()
        if not group:
            return {}

        products = []
        async with db.execute("PRAGMA table_info(products)") as cur:
            product_columns = {row[1] for row in await cur.fetchall()}
        room_filter = "AND (room_id IS NULL OR room_id = ?)" if "room_id" in product_columns else ""
        room_order = "CASE WHEN room_id = ? THEN 0 ELSE 1 END," if "room_id" in product_columns else ""
        if product_id:
            async with db.execute(
                """SELECT * FROM products
                   WHERE enabled = 1 AND (product_id = ? OR CAST(id AS TEXT) = ?)
                   LIMIT 10""",
                (str(product_id), str(product_id)),
            ) as cur:
                products = [dict(r) for r in await cur.fetchall()]
        if not products:
            room_id = group["room_id"]
            params = (room_id, room_id) if "room_id" in product_columns else ()
            async with db.execute(
                f"""SELECT * FROM products
                   WHERE enabled = 1 {room_filter}
                   ORDER BY {room_order} id DESC
                   LIMIT 30""",
                params,
            ) as cur:
                products = [dict(r) for r in await cur.fetchall()]

        async with db.execute(
            """SELECT filename FROM recordings
               WHERE group_id = ? AND transcribed = 2
               ORDER BY id DESC LIMIT 5""",
            (group_id,),
        ) as cur:
            recs = await cur.fetchall()

    recordings_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "recordings"))
    srt_texts: List[str] = []
    for rec in recs:
        srt_path = os.path.join(recordings_dir, os.path.splitext(rec["filename"])[0] + ".srt")
        if not os.path.exists(srt_path):
            continue
        try:
            with open(srt_path, encoding="utf-8") as f:
                srt_texts.append(f.read()[:8000])
        except Exception:
            pass

    group_dict = dict(group)
    director_script = group_dict.get("director_script") or ""
    try:
        if director_script:
            director_script = json.dumps(json.loads(director_script), ensure_ascii=False)
    except Exception:
        pass

    return {
        "group": group_dict,
        "products": products,
        "srt_text": "\n".join(srt_texts),
        "director_script_text": str(director_script)[:8000],
    }


def score_product_match(context: Dict, product_id: Optional[str] = None, keywords: Optional[List[str]] = None, threshold: float = 0.58) -> Dict:
    group = context.get("group") or {}
    products = context.get("products") or []
    corpus = " ".join([
        group.get("label") or "",
        group.get("wig_model") or "",
        group.get("wig_color") or "",
        context.get("srt_text") or "",
        context.get("director_script_text") or "",
    ]).lower()

    requested = _tokens(product_id, keywords)
    group_tokens = _tokens(group.get("label"), group.get("wig_model"), group.get("wig_color"))
    best = {"score": 0.0, "product": None, "hits": [], "missing": requested, "threshold": threshold}

    candidates = products or [None]
    for product in candidates:
        product_tokens = []
        if product:
            product_tokens = _tokens(product.get("product_id"), product.get("product_name"), product.get("keywords"))
        candidate_tokens = list(dict.fromkeys(requested + product_tokens + group_tokens))
        if not candidate_tokens:
            candidate_tokens = group_tokens
        hit_score, hits = _contains_score(corpus, candidate_tokens, 1.0)

        exact_bonus = 0.0
        if product_id and product and str(product_id) in {str(product.get("product_id")), str(product.get("id"))}:
            exact_bonus = 0.25
        color = (group.get("wig_color") or "").lower()
        if color and color in corpus:
            exact_bonus += 0.10
        label = (group.get("label") or "").lower()
        if label and label != "未分类" and label in corpus:
            exact_bonus += 0.08
        score = min(1.0, hit_score + exact_bonus)
        if score > best["score"]:
            best = {
                "score": round(score, 3),
                "product": product,
                "hits": hits,
                "missing": [t for t in candidate_tokens if t not in hits][:12],
                "threshold": threshold,
            }

    best["ok"] = best["score"] >= threshold
    if not best["ok"]:
        best["reason"] = f"商品强匹配不足: {best['score']:.2f} < {threshold:.2f}; hits={','.join(best['hits'][:8]) or 'none'}"
    return best


class QianchuanMatcher(SemanticMatcher):
    """Semantic matcher with Qianchuan shot-bias metadata."""

    def _qianchuan_bias(self, segment: Dict, text: str) -> float:
        text_l = text.lower()
        score = 0.0
        keywords = segment.get("visual_keywords") or segment.get("priority_shots") or []
        for kw in keywords:
            if str(kw).lower() in text_l:
                score += 0.25
        for kw, weight in POSITIVE_SHOT_KEYWORDS.items():
            if kw.lower() in text_l:
                score += weight * 0.08
        for kw, weight in NEGATIVE_SHOT_KEYWORDS.items():
            if kw.lower() in text_l:
                score += weight * 0.10
        return score

    async def match_qianchuan_segments(self, script_segments: List[Dict], group_id: int) -> List[Dict]:
        matched = await self.match_segments_to_recordings(script_segments, group_id)
        for item in matched:
            seg = item.get("script_segment") or {}
            text = " ".join([seg.get("text") or seg.get("voiceover_text") or "", " ".join(seg.get("visual_keywords") or [])])
            bias = self._qianchuan_bias(seg, text)
            item["qianchuan_shot_score"] = round(max(0.0, item.get("confidence_score", 0.0) + bias), 3)
            item["edit_actions"] = _edit_actions_for_scene(seg.get("scene_type", ""), seg)
        return matched


def _edit_actions_for_scene(scene_type: str, segment: Dict) -> List[Dict]:
    """Return GPU/ffmpeg-consumable segment metadata for premium ad edits."""
    mapping = {
        "result_hook": [{"type": "push_in", "intensity": 0.10}, {"type": "keyword_pop"}],
        "pain_point": [{"type": "crop_zoom", "region": "face_upper", "intensity": 0.12}],
        "product_proof": [{"type": "detail_zoom", "region": "hairline_or_color", "intensity": 0.22}, {"type": "pip", "layout": "detail_top_right"}],
        "tryon_result": [{"type": "pan", "direction": "left_to_right"}, {"type": "pull_out", "intensity": 0.08}],
        "cta": [{"type": "push_in", "intensity": 0.08}, {"type": "keyword_pop"}],
    }
    return mapping.get(scene_type, [{"type": "push_in", "intensity": 0.06}])
