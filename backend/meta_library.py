"""
Local meta library — pre-generated publish copy that can be used as a fallback
when the LLM (Bedrock) is unreachable.

Usage:
  await seed_library(100)          # one-time background seeding
  await get_random_schemes(4)      # returns 4 random entries (one per type)
  await get_library_count()        # how many entries are stored
"""
import asyncio
import logging
import random
from typing import Dict, List, Optional

import aiosqlite

from db import DB_PATH
from meta_generator import _META_PROMPT, _call_bedrock

logger = logging.getLogger(__name__)

# ── Seed data pools used when generating generic entries ─────────────────────

_SEED_WIGS = [
    ("自然卷发", "自然黑"),
    ("直发BOB头", "冷棕"),
    ("长波浪卷", "暖棕"),
    ("短发蘑菇头", "奶茶棕"),
    ("中长渐变", "亚麻金"),
    ("丸子头刘海", "酒红"),
    ("长直发", "深蓝黑"),
    ("空气感卷发", "樱花粉"),
    ("梨花头", "琥珀棕"),
    ("微卷中长发", "银灰"),
    ("高马尾发片", "自然黑"),
    ("斜刘海长波浪", "暖棕"),
]

_SEED_SRTS = [
    "这款发色真的超好看，显白效果特别好，发丝质感很顺滑，大家在直播间可以看一下",
    "戴上去完全不会掉，固定效果很好，透气性也不错，发量稀少的宝子特别适合",
    "这个颜色在阳光下特别好看，会有一点点反光，非常显气质，我们今天直播间价格是全网最低",
    "这款很适合职场，看起来干练又不失温柔，发质很好摸起来非常真实",
    "佩戴方法很简单，对新手友好，我来示范一下怎么戴更自然，大家可以跟着做",
    "这个款式今年很流行，上头率非常高，不管什么脸型戴上去都很好看",
    "发量少的宝子有福了，这款蓬松度特别好，戴上去立刻显得发量很多",
    "这是我们店里卖得最好的一款，回购率特别高，今天直播间有优惠",
]

_VARIATION_HINTS = [
    "强调发色光泽与视觉冲击，突出颜色名称",
    "聚焦佩戴舒适度与轻盈感，从使用体验切入",
    "侧重社交场合：约会/职场/聚会等具体情境",
    "主打性价比与品质工艺细节",
    "从发量少/发质受损痛点切入，强调解决方案",
    "强调发型款式的流行感与时尚属性",
    "聚焦造型多样性：可拉直/卷/扎等多种变换",
    "从妈妈/职场女性/学生等具体人群视角切入",
]


# ── DB helpers ────────────────────────────────────────────────────────────────

async def get_library_count() -> int:
    try:
        async with aiosqlite.connect(DB_PATH, timeout=60) as db:
            async with db.execute("SELECT COUNT(*) FROM meta_library") as cur:
                row = await cur.fetchone()
                return row[0] if row else 0
    except Exception:
        return 0


async def get_random_schemes(count: int = 7) -> List[Dict]:
    """Return up to `count` random entries from the library, one per scheme type if possible."""
    try:
        async with aiosqlite.connect(DB_PATH, timeout=60) as db:
            db.row_factory = aiosqlite.Row
            # Try to get one of each type first
            types = ["种草", "催单", "产品介绍", "教学", "痛点", "场景", "消除担忧"]
            schemes = []
            for t in types[:count]:
                async with db.execute(
                    "SELECT * FROM meta_library WHERE type=? ORDER BY RANDOM() LIMIT 1", (t,)
                ) as cur:
                    row = await cur.fetchone()
                if row:
                    schemes.append({
                        "type": row["type"],
                        "title": row["title"],
                        "description": row["description"],
                        "tags": row["tags"],
                    })
            # Fill remaining slots with any random if needed
            if len(schemes) < count:
                need = count - len(schemes)
                async with db.execute(
                    "SELECT * FROM meta_library ORDER BY RANDOM() LIMIT ?", (need,)
                ) as cur:
                    rows = await cur.fetchall()
                for row in rows:
                    schemes.append({
                        "type": row["type"],
                        "title": row["title"],
                        "description": row["description"],
                        "tags": row["tags"],
                    })
            return schemes
    except Exception as e:
        logger.error(f"get_random_schemes failed: {e}")
        return []


async def _save_schemes(schemes: List[Dict]) -> int:
    """Persist a list of scheme dicts. Returns number saved."""
    if not schemes:
        return 0
    try:
        async with aiosqlite.connect(DB_PATH, timeout=60) as db:
            for s in schemes:
                await db.execute(
                    "INSERT INTO meta_library (type, title, description, tags) VALUES (?, ?, ?, ?)",
                    (s.get("type", "种草"), s.get("title", ""), s.get("description", ""), s.get("tags", "")),
                )
            await db.commit()
        return len(schemes)
    except Exception as e:
        logger.error(f"_save_schemes failed: {e}")
        return 0


# ── Background seeder ─────────────────────────────────────────────────────────

async def seed_library(target_count: int = 100) -> int:
    """
    Generate and store meta entries until the library has at least `target_count` entries.
    Designed to run as a FastAPI BackgroundTask.
    Returns the number of new entries added.
    """
    current = await get_library_count()
    need = max(0, target_count - current)
    if need == 0:
        logger.info(f"meta_library already has {current} entries, skipping seed")
        return 0

    logger.info(f"Seeding meta_library: need {need} more (currently {current})")
    added = 0
    batch = 0

    while added < need:
        wig_model, wig_color = _SEED_WIGS[batch % len(_SEED_WIGS)]
        srt = _SEED_SRTS[batch % len(_SEED_SRTS)]
        variation_hint = _VARIATION_HINTS[batch % len(_VARIATION_HINTS)]

        prompt = _META_PROMPT.format(
            anti_repetition_block="",
            wig_model=wig_model,
            wig_color=wig_color,
            labels="假发",
            srt_excerpt=srt,
            variation_hint=variation_hint,
        )

        result = await _call_bedrock(prompt, max_tokens=3600)
        if result and result.get("schemes"):
            schemes = []
            for s in result["schemes"]:
                tags = s.get("tags", [])
                tags_str = ",".join(tags) if isinstance(tags, list) else str(tags)
                schemes.append({
                    "type": s.get("type", "种草"),
                    "title": s.get("title", ""),
                    "description": s.get("description", ""),
                    "tags": tags_str,
                })
            n = await _save_schemes(schemes)
            added += n
            logger.info(f"meta_library seed: +{n} entries (total added {added}/{need})")
        else:
            logger.warning(f"meta_library seed batch {batch + 1} failed, continuing")

        batch += 1
        if added < need:
            await asyncio.sleep(1)

    logger.info(f"meta_library seeding complete: {added} new entries added")
    return added
