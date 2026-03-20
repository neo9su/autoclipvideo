"""Generate publish content (title/caption/hashtags) for merged videos via Bedrock LLM."""
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

_PUBLISH_PROMPT = """你是一名专业的抖音短视频运营，擅长为假发产品直播视频撰写吸引眼球的发布文案。

产品信息：
- 款式：{wig_model}
- 颜色：{wig_color}

直播内容摘要：
{text}

请生成抖音发布内容，以JSON格式返回（只返回JSON，不含其他内容）：
{{
  "title": "视频标题（≤20字，吸引眼球，包含产品特点）",
  "caption": "发布文案（≤150字，包含产品亮点、适合场景，自然融入种草语气）",
  "hashtags": ["话题1", "话题2", "话题3", "话题4", "话题5"]
}}

hashtags 要包含：假发相关通用话题（如假发、变美日记）+ 产品特定话题，不要加#号。"""


def _srt_to_text(srt_path: str, max_chars: int = 1000) -> str:
    try:
        with open(srt_path, encoding="utf-8") as f:
            content = f.read()
        lines = []
        for line in content.splitlines():
            line = line.strip()
            if not line or re.match(r"^\d+$", line) or re.match(r"^\d{2}:\d{2}:\d{2}", line):
                continue
            lines.append(line)
        return " ".join(lines)[:max_chars]
    except Exception as e:
        logger.error(f"SRT read error {srt_path}: {e}")
        return ""


async def generate_publish_content(group_id: int) -> Optional[dict]:
    """Call Bedrock to generate title/caption/hashtags for a group's merged video."""
    if not BEDROCK_TOKEN:
        logger.error("AWS_BEARER_TOKEN_BEDROCK not set")
        return None

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT wig_model, wig_color FROM clip_groups WHERE id = ?", (group_id,)
        ) as cur:
            group = await cur.fetchone()
        if not group:
            return None

        async with db.execute(
            """SELECT clip_filename, filename
               FROM recordings
               WHERE group_id = ? AND clipped = 2
               ORDER BY start_time ASC""",
            (group_id,),
        ) as cur:
            recs = await cur.fetchall()

    wig_model = group["wig_model"] or "未知款式"
    wig_color = group["wig_color"] or "未知颜色"

    texts = []
    for r in recs:
        base = r["clip_filename"] or r["filename"]
        srt_path = os.path.join(RECORDINGS_DIR, os.path.splitext(base)[0] + ".srt")
        t = _srt_to_text(srt_path)
        if t:
            texts.append(t)
    combined_text = " ".join(texts)[:3000] if texts else f"{wig_model} {wig_color} 假发产品展示"

    prompt = _PUBLISH_PROMPT.format(
        wig_model=wig_model, wig_color=wig_color, text=combined_text
    )
    payload = {
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": {"maxTokens": 600, "temperature": 0.7},
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


