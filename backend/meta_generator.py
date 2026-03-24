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

_META_PROMPT = """你是一位专注于「精致女性生活方式」赛道的抖音内容运营，负责为假发短视频撰写发布文案。

目标受众：16-40岁女性，追求精致日常、注重颜值管理，有一定消费力，对美发造型感兴趣。
内容基调：自信、精致、有共鸣感；像闺蜜分享好物，而非促销吆喝。

产品信息：
- 假发款式：{wig_model}
- 颜色：{wig_color}
- 内容标签：{labels}
- 字幕摘要（直播片段）：{srt_excerpt}

请以JSON格式返回（只返回JSON，不含任何其他内容）：
{{
  "title": "标题",
  "description": "描述正文",
  "tags": ["#标签1", "#标签2", "#标签3", "#标签4", "#标签5", "#标签6", "#标签7"]
}}

【标题要求】25字以内，突出颜值变化或生活场景，带情绪感染力。
可用角度（选最契合的一个）：
- 发型改造：「这顶假发让我多拍了20张照」「换个发色，整个人精神了」
- 痛点解决：「发量稀少救星」「扁塌刘海的解法」「头皮过敏也能戴」
- 精致日常：「上班、约会、聚会一顶搞定」「通勤不将就」
禁止：节日/节气词（过年/春节/元旦等）、时间限定词（今天/这周/最后X单）、夸大促销感（抢/秒/最后）。

【描述要求】120-180字，分3段自然衔接：
1. 共鸣开场（1-2句）：描述目标用户的真实场景或痛点，让她觉得「这说的就是我」
2. 产品亮点（3-4句）：结合字幕摘要提炼2-3个核心卖点，口语化、有画面感，不堆砌参数
3. 互动收尾（1句）：开放式提问或邀请分享，如「你们平时更偏爱哪种风格？」
禁止：节日/时令/限时词汇；「姐妹」可用但不要超过2次；不用「绝绝子/yyds」等已过时网络词。

【标签要求】7-10个，#格式，覆盖：
- 品类词：#假发 #仿真假发 等
- 款式/颜色：与产品直接相关
- 场景/人群：#精致日常 #通勤穿搭 #发量少救星 等
- 情绪/风格：#变美打卡 #颜值管理 等
禁止时效性标签（#新年 #春节 等）。"""


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
        async with httpx.AsyncClient(timeout=30.0) as client:
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

    result = await _call_bedrock(prompt, max_tokens=900)
    if not result:
        return None

    tags = result.get("tags", [])
    if isinstance(tags, list):
        tags_str = ",".join(tags)
    else:
        tags_str = str(tags)

    return {
        "title": result.get("title", ""),
        "description": result.get("description", ""),
        "tags": tags_str,
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
