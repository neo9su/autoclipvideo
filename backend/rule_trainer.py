"""
Phase 3 – Auto-learning rule trainer.

Analyzes clip_reviews to compute per-keyword false-positive rates and generate
rule adjustment suggestions. Suggestions are stored in rule_suggestions for
user confirmation before being applied to Phase 1 (_SCORES_EFFECTIVE).

Usage:
    from rule_trainer import run_training_cycle
    await run_training_cycle()
"""

import json
import logging
from collections import defaultdict

import aiosqlite

from db import DB_PATH

logger = logging.getLogger(__name__)

# Thresholds for generating suggestions
FP_HIGH     = 0.85   # above this → suggest remove (score→0)
FP_MEDIUM   = 0.50   # above this → suggest reduce
MIN_SAMPLES = 5      # minimum observations per keyword to generate suggestion


async def compute_keyword_stats(min_samples: int = MIN_SAMPLES) -> dict[str, dict]:
    """
    For each keyword in _SCORES_EFFECTIVE, compute:
      kept:    segments containing keyword that user kept (true positive)
      removed: segments containing keyword that user removed (false positive)
      added:   segments containing keyword that were in user_added (algo missed)

    Returns {keyword: {kept, removed, added, fp_rate, fn_rate, total}}
    """
    from editor import _SCORES_EFFECTIVE

    async with aiosqlite.connect(DB_PATH, timeout=60) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT cr.algo_segments, cr.user_segments, cr.user_segments_full,
                   cr.user_added, cr.user_removed,
                   r.review_candidates
            FROM clip_reviews cr
            JOIN recordings r ON cr.recording_id = r.id
            WHERE cr.is_valid_sample = 1
              AND r.review_candidates IS NOT NULL
        """) as cur:
            reviews = await cur.fetchall()

    if not reviews:
        return {}

    stats: dict[str, dict] = defaultdict(lambda: {"kept": 0, "removed": 0, "added": 0})

    for row in reviews:
        try:
            review_data  = json.loads(row["review_candidates"])
            algo_idxs    = set(json.loads(row["algo_segments"]  or "[]"))
            user_idxs    = set(json.loads(row["user_segments"]  or "[]"))
            user_added_idxs   = set(json.loads(row["user_added"]  or "[]"))
            user_removed_idxs = set(json.loads(row["user_removed"] or "[]"))
        except Exception as e:
            logger.debug(f"rule_trainer: skipping malformed review row: {e}")
            continue

        all_segs: dict[int, dict] = {
            s["idx"]: s for s in review_data.get("all_segs", [])
        }

        # Build text map: for user_added we use user_segments_full if available
        try:
            user_segs_full = {
                s["idx"]: s
                for s in json.loads(row["user_segments_full"] or "[]")
            }
        except Exception:
            user_segs_full = {}

        def _text(idx: int) -> str:
            seg = user_segs_full.get(idx) or all_segs.get(idx, {})
            return seg.get("text", "")

        for idx in (algo_idxs & user_idxs):          # true positives (kept)
            text = _text(idx)
            for kw in _SCORES_EFFECTIVE:
                if kw in text:
                    stats[kw]["kept"] += 1

        for idx in user_removed_idxs:                 # false positives (removed)
            text = _text(idx)
            for kw in _SCORES_EFFECTIVE:
                if kw in text:
                    stats[kw]["removed"] += 1

        for idx in user_added_idxs:                   # false negatives (user added)
            text = _text(idx)
            for kw in _SCORES_EFFECTIVE:
                if kw in text:
                    stats[kw]["added"] += 1

    # Compute rates
    result: dict[str, dict] = {}
    for kw, s in stats.items():
        total = s["kept"] + s["removed"]
        if total < min_samples:
            continue
        result[kw] = {
            **s,
            "total":   total,
            "fp_rate": s["removed"] / total,
            "fn_rate": s["added"]   / (total + s["added"]) if (total + s["added"]) else 0,
        }

    return result


async def generate_suggestions(overwrite_pending: bool = True) -> list[dict]:
    """
    Compute keyword stats and produce rule_suggestions rows.
    Returns list of suggestion dicts actually written to DB.
    """
    from editor import _SCORES_EFFECTIVE

    kw_stats = await compute_keyword_stats()
    if not kw_stats:
        return []

    suggestions = []
    for kw, s in kw_stats.items():
        current_score = _SCORES_EFFECTIVE.get(kw, 0.0)
        fp_rate       = s["fp_rate"]
        sample_count  = s["total"]

        if fp_rate >= FP_HIGH and sample_count >= MIN_SAMPLES:
            # Suggest remove
            suggestions.append({
                "source":          "stats",
                "keyword":         kw,
                "current_score":   current_score,
                "suggested_score": 0.0,
                "reason":          f"误报率 {fp_rate:.0%}（{s['removed']}/{sample_count} 次被删除），建议移除",
                "evidence":        json.dumps({
                    "fp_rate": round(fp_rate, 3),
                    "sample_count": sample_count,
                    "removed": s["removed"],
                    "kept": s["kept"],
                }),
            })

        elif fp_rate >= FP_MEDIUM and sample_count >= MIN_SAMPLES:
            # Suggest reduce: scale by (1 - fp_rate), round to nearest 0.5
            raw = current_score * (1.0 - fp_rate)
            new_score = max(1.0, round(raw * 2) / 2)
            if new_score >= current_score:
                continue
            suggestions.append({
                "source":          "stats",
                "keyword":         kw,
                "current_score":   current_score,
                "suggested_score": new_score,
                "reason":          f"误报率 {fp_rate:.0%}（{s['removed']}/{sample_count} 次被删除），建议降分 {current_score} → {new_score}",
                "evidence":        json.dumps({
                    "fp_rate": round(fp_rate, 3),
                    "sample_count": sample_count,
                    "removed": s["removed"],
                    "kept": s["kept"],
                }),
            })

    if not suggestions:
        return []

    async with aiosqlite.connect(DB_PATH, timeout=60) as db:
        if overwrite_pending:
            await db.execute(
                "DELETE FROM rule_suggestions WHERE source='stats' AND status='pending'"
            )

        for s in suggestions:
            # Skip if same suggestion already accepted/rejected
            async with db.execute(
                "SELECT id FROM rule_suggestions WHERE keyword=? AND status IN ('accepted','rejected')",
                (s["keyword"],),
            ) as cur:
                if await cur.fetchone():
                    continue

            await db.execute("""
                INSERT INTO rule_suggestions
                    (source, keyword, current_score, suggested_score, reason, evidence, status)
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
            """, (
                s["source"], s["keyword"], s["current_score"],
                s["suggested_score"], s["reason"], s["evidence"],
            ))

        await db.commit()

    logger.info(f"rule_trainer: generated {len(suggestions)} suggestions from {len(kw_stats)} keywords")
    return suggestions


async def run_training_cycle() -> dict:
    """Entry point: analyze reviews → write suggestions → return summary."""
    async with aiosqlite.connect(DB_PATH, timeout=60) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM clip_reviews WHERE is_valid_sample=1"
        ) as cur:
            row = await cur.fetchone()
        sample_count = row[0] if row else 0

    if sample_count < MIN_SAMPLES:
        logger.info(f"rule_trainer: only {sample_count} valid samples (need {MIN_SAMPLES}), skipping")
        return {"status": "insufficient_samples", "sample_count": sample_count}

    suggestions = await generate_suggestions()
    return {
        "status": "ok",
        "sample_count": sample_count,
        "suggestions_generated": len(suggestions),
    }


async def load_overrides_from_db() -> dict[str, float]:
    """Load accepted rule overrides from DB. Called at startup."""
    async with aiosqlite.connect(DB_PATH, timeout=60) as db:
        async with db.execute("SELECT keyword, score FROM rule_overrides") as cur:
            rows = await cur.fetchall()
    return {r[0]: r[1] for r in rows}
