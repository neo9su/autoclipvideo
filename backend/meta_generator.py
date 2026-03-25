"""
LLM-based publish metadata generator.
Generates title / description / tags for a clip_group using Bedrock.
"""
import json
import logging
import os
import re
from typing import Optional

import aiosqlite
import httpx

from db import DB_PATH

logger = logging.getLogger(__name__)

BEDROCK_URL = "https://bedrock-runtime.us-east-1.amazonaws.com"
BEDROCK_MODEL = os.environ.get("BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-6")
BEDROCK_TOKEN = os.environ.get("AWS_BEARER_TOKEN_BEDROCK", "")
RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), "..", "recordings")

_META_PROMPT = """你是一位专注于「精致女性生活方式」赛道的抖音内容运营，负责为假发短视频撰写多套发布文案方案。

目标受众：16-40岁女性，追求精致日常、注重颜值管理，有一定消费力，对美发造型感兴趣。

产品信息：
- 假发款式：{wig_model}
- 颜色：{wig_color}
- 内容标签：{labels}
- 字幕摘要（直播片段）：{srt_excerpt}

请分析视频内容，生成以下4种方案（每种方案独立完整）。以JSON格式返回（只返回JSON，不含任何其他内容）：

{{
  "schemes": [
    {{
      "type": "种草",
      "title": "...",
      "description": "...",
      "tags": ["#标签1", "#标签2", "..."]
    }},
    {{
      "type": "催单",
      "title": "...",
      "description": "...",
      "tags": ["#标签1", "#标签2", "..."]
    }},
    {{
      "type": "产品介绍",
      "title": "...",
      "description": "...",
      "tags": ["#标签1", "#标签2", "..."]
    }},
    {{
      "type": "教学",
      "title": "...",
      "description": "...",
      "tags": ["#标签1", "#标签2", "..."]
    }}
  ]
}}

【通用禁止】节日/节气词（过年/春节/元旦等）；「姐妹」不超过2次；不用「绝绝子/yyds/爱了爱了」等过时词；禁止时效性标签。
【标签要求】每种方案7-10个#标签，覆盖品类词、款式颜色、场景人群、情绪种草。

─────────────────────────────────
【方案1 · 种草】内容基调：自信、精致、有场景感；像闺蜜分享真实美好瞬间。
标题（≤25字）：优先场景角度，带情绪感染力。
  ▸ 场景种草：「出门五分钟，发型直接满级」「约会当天靠它救场」「通勤妆发一套搞定」
  ▸ 颜值升级：「换了这个发色，被夸了一整天」「整个人气质都不一样了」
描述（120-180字）：
  1. 场景代入（1-2句）：第一/第二人称，制造画面感
  2. 种草展示（3-4句）：结合字幕提炼1-2个核心亮点，口语化有画面感
  3. 互动收尾（1句）：开放式提问

─────────────────────────────────
【方案2 · 催单】内容基调：紧迫感 + 价值感，驱动粉丝从视频跳转下单。
标题（≤25字）：点出直播间同价/小黄车等关键词，让没看直播的粉丝觉得「这个机会不能错过」。
  示例：「错过直播？同款同价在这里」「直播间爆款 视频也能下单」「没赶上直播也能买到」
描述（100-150字）：
  1. 关联直播（1句）：「最近直播间很多宝子在问这款...」
  2. 产品核心亮点（2-3句）：简洁说出1-2个最强卖点
  3. 催单引导（1-2句）：「直播间同价，宝子们点左下方小黄车就可以下单」「库存有限，想要的宝子抓紧」
禁止夸大/虚假紧迫感；不用「最后X单/限时」等硬广措辞。

─────────────────────────────────
【方案3 · 产品介绍】内容基调：专业、清晰、有说服力，帮助观众了解产品细节。
标题（≤25字）：突出产品核心特点或使用场景。
  示例：「这款Bob头到底有多仙」「{wig_color}发色上头合集」「详解这款假发的3个优点」
描述（120-180字）：
  1. 引出产品（1句）：自然介绍这款产品
  2. 详细介绍（4-5句）：结合字幕摘要，说明款式、颜色、材质、佩戴感、适合场景等，选最相关的讲
  3. 适合人群（1句）：「发量少/发质受损/想尝试新造型的宝子都适合」
  4. 互动（1句）：「有问题评论区告诉我」

─────────────────────────────────
【方案4 · 教学】内容基调：实用、亲切，让观众觉得「我也能做到」。
仅在字幕摘要中出现佩戴步骤/搭配技巧/护理方法等教学内容时使用；若无相关内容，仍需生成但可以基于通用假发使用技巧。
标题（≤25字）：「一招教你」「手把手」「学会这个」等教学感句式。
  示例：「手把手教你戴出自然感」「一招让假发更服帖」「这样搭才不显假」
描述（120-180字）：
  1. 引出痛点（1-2句）：「很多宝子反映假发戴起来不自然...」
  2. 教学步骤（3-4句）：结合字幕中的具体技巧展开，动作感强，口语化
  3. 效果展示（1句）：说出做完之后的效果
  4. 互动（1句）：「学会了吗？有问题评论区问我」"""


async def _call_bedrock(prompt: str, max_tokens: int = 600) -> Optional[dict]:
    if not BEDROCK_TOKEN:
        logger.error("AWS_BEARER_TOKEN_BEDROCK not set")
        return None
    payload = {
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": {"maxTokens": max_tokens, "temperature": 0.7},
    }
    url = f"{BEDROCK_URL}/model/{BEDROCK_MODEL}/converse"
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {BEDROCK_TOKEN}",
                    "Content-Type": "application/json",
                },
            )
        if resp.status_code != 200:
            logger.error(f"Bedrock error {resp.status_code}: {resp.text[:300]}")
            return None
        raw = resp.json()["output"]["message"]["content"][0]["text"]
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            return json.loads(m.group())
        logger.error(f"No JSON in Bedrock response: {raw[:200]}")
    except Exception as e:
        logger.error(f"Bedrock call failed: {e}")
    return None


def _get_srt_excerpt(merged_filename: Optional[str], max_chars: int = 800) -> str:
    """Extract a short text sample from the group's merged SRT if available."""
    if not merged_filename:
        return ""
    srt_path = os.path.join(
        RECORDINGS_DIR,
        os.path.splitext(merged_filename)[0] + ".srt",
    )
    if not os.path.exists(srt_path):
        return ""
    try:
        with open(srt_path, encoding="utf-8") as f:
            content = f.read()
        lines = []
        for line in content.splitlines():
            line = line.strip()
            if not line or re.match(r"^\d+$", line) or re.match(r"^\d{2}:\d{2}:\d{2}", line):
                continue
            lines.append(line)
        text = " ".join(lines)
        return text[:max_chars]
    except Exception:
        return ""


async def generate_meta(group_id: int) -> Optional[dict]:
    """
    Generate publish metadata for a clip_group.
    Returns dict with keys: title, description, tags (comma-separated string).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT g.wig_model, g.wig_color, g.merged_filename,
                      GROUP_CONCAT(DISTINCT r.session_label) as labels
               FROM clip_groups g
               LEFT JOIN recordings r ON r.group_id = g.id
               WHERE g.id = ?
               GROUP BY g.id""",
            (group_id,),
        ) as cur:
            group = await cur.fetchone()

    if not group:
        logger.error(f"Group {group_id} not found")
        return None

    srt_excerpt = _get_srt_excerpt(group["merged_filename"])
    prompt = _META_PROMPT.format(
        wig_model=group["wig_model"] or "未知款式",
        wig_color=group["wig_color"] or "未知颜色",
        labels=group["labels"] or "无",
        srt_excerpt=srt_excerpt or "无字幕",
    )

    result = await _call_bedrock(prompt, max_tokens=2400)
    if not result:
        return None

    # New multi-scheme format: {"schemes": [{type, title, description, tags}, ...]}
    schemes_raw = result.get("schemes", [])
    if schemes_raw:
        schemes = []
        for s in schemes_raw:
            tags = s.get("tags", [])
            tags_str = ",".join(tags) if isinstance(tags, list) else str(tags)
            schemes.append({
                "type": s.get("type", "种草"),
                "title": s.get("title", ""),
                "description": s.get("description", ""),
                "tags": tags_str,
            })
        return {"schemes": schemes}

    # Fallback: legacy single-scheme response
    tags = result.get("tags", [])
    tags_str = ",".join(tags) if isinstance(tags, list) else str(tags)
    return {
        "schemes": [{
            "type": "种草",
            "title": result.get("title", ""),
            "description": result.get("description", ""),
            "tags": tags_str,
        }]
    }


# ── Product keyword matching ──────────────────────────────────────────────────

async def match_product(group_id: int) -> Optional[dict]:
    """
    Match a product from the products table for a clip_group.
    Returns the best-matching product dict, or None.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT wig_model, wig_color FROM clip_groups WHERE id = ?", (group_id,)
        ) as cur:
            group = await cur.fetchone()
        if not group:
            return None

        async with db.execute(
            "SELECT * FROM products WHERE enabled = 1"
        ) as cur:
            products = await cur.fetchall()

    keywords = [k for k in [group["wig_model"], group["wig_color"]] if k]
    if not keywords:
        return None

    # Score each product: exact match > substring match
    best_score = 0
    best_product = None
    for p in products:
        product_keywords = [kw.strip() for kw in (p["keywords"] or "").split(",") if kw.strip()]
        score = 0
        for kw in keywords:
            if kw in product_keywords:
                score += 2  # exact
            elif any(kw in pk or pk in kw for pk in product_keywords):
                score += 1  # substring
        if score > best_score:
            best_score = score
            best_product = dict(p)

    return best_product
