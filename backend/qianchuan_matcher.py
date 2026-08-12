"""千川投流版商品与镜头强匹配。

低于阈值时调用方必须拒绝生成，避免错品/错色投流素材。
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, Iterable, List, Optional, Tuple

import aiosqlite
from srt_resolver import resolve_srt_path

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

# Qianchuan uses stricter, isolated thresholds. Director matching is unchanged.
MIN_QIANCHUAN_RELEVANCE = 0.42
MIN_QIANCHUAN_SEMANTIC_SCORE = 0.30


def _normalise_text(value: object) -> str:
    return re.sub(r"[\s\u3000\u3002，。！？、；：,.!?;:/|]+", "", str(value or "").lower())


def assess_segment_relevance(segment: Dict, source_text: str, confidence_score: float) -> Dict:
    """Conservatively assess script-to-source relevance with auditable reasons."""
    source = _normalise_text(source_text)
    voiceover = segment.get("voiceover_text") or segment.get("text") or ""
    requirements = _tokens(segment.get("visual_keywords"), segment.get("priority_shots"))
    required_hits = [term for term in requirements if _normalise_text(term) in source]
    script_tokens = _tokens(voiceover)
    script_hits = [token for token in script_tokens if _normalise_text(token) in source]
    clean_voiceover = _normalise_text(voiceover)
    voice_grams = {clean_voiceover[index:index + 2] for index in range(max(0, len(clean_voiceover) - 1))}
    source_grams = {source[index:index + 2] for index in range(max(0, len(source) - 1))}
    gram_score = len(voice_grams & source_grams) / max(1, len(voice_grams))
    contradiction_terms = [term for term in NEGATIVE_SHOT_KEYWORDS if _normalise_text(term) in source]
    requirement_score = len(required_hits) / max(1, len(requirements))
    text_score = max(min(1.0, len(script_hits) / max(2, len(script_tokens))), gram_score)
    confidence = max(0.0, min(1.0, float(confidence_score or 0.0)))
    score = max(0.0, min(1.0, confidence * 0.55 + text_score * 0.25 + requirement_score * 0.20))
    reasons = []
    if not source_text.strip():
        reasons.append("missing_source_transcript")
    if contradiction_terms:
        reasons.append("contradictory_evidence:" + ",".join(contradiction_terms[:4]))
    if confidence < MIN_QIANCHUAN_SEMANTIC_SCORE:
        reasons.append(f"semantic_score_below_{MIN_QIANCHUAN_SEMANTIC_SCORE:.2f}")
    if score < MIN_QIANCHUAN_RELEVANCE:
        reasons.append(f"relevance_below_{MIN_QIANCHUAN_RELEVANCE:.2f}")
    return {"ok": not reasons, "score": round(score, 3),
            "confidence_score": round(confidence, 3), "text_score": round(text_score, 3),
            "requirement_score": round(requirement_score, 3),
            "required_terms": requirements, "required_hits": required_hits,
            "source_text": source_text[:500], "reasons": reasons,
            "evidence_type": "srt_transcript_proxy"}


def audit_qianchuan_segments(matched_segments: List[Dict], audio_segments: Optional[List[Dict]] = None) -> Dict:
    """Audit every segment, including audio duration alignment and rejection reasons."""
    audio_by_scene = {item.get("scene_id"): item for item in (audio_segments or [])}
    records = []
    for item in matched_segments:
        segment = item.get("script_segment") or {}
        relevance = item.get("relevance") or assess_segment_relevance(
            segment, item.get("matched_source_text") or "", item.get("confidence_score", 0.0))
        audio = audio_by_scene.get(segment.get("scene_id"), {})
        expected = float(audio.get("duration") or segment.get("duration") or 0)
        actual = float(item.get("matched_duration") or 0)
        timeline_ok = actual >= max(1.0, expected * 0.85) if expected else actual > 0
        if not timeline_ok:
            relevance = {**relevance, "ok": False,
                         "reasons": [*relevance["reasons"], "matched_clip_shorter_than_audio"]}
        records.append({"scene_id": segment.get("scene_id"),
                        "scene_type": segment.get("scene_type"),
                        "matched_recording_id": item.get("matched_recording_id"),
                        "start": item.get("matched_start_time"), "duration": actual,
                        "timeline_ok": timeline_ok, "relevance": relevance})
    rejected = [record for record in records if not record["relevance"]["ok"]]
    return {"ok": bool(records) and not rejected, "segments": records,
            "accepted_count": len(records) - len(rejected), "rejected_count": len(rejected),
            "rejection_reasons": [reason for record in rejected for reason in record["relevance"]["reasons"]]}


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

    srt_texts: List[str] = []
    from media_contract import resolve_srt_file
    for rec in recs:
        srt_path = resolve_srt_file(rec["filename"])
        if srt_path is None:
