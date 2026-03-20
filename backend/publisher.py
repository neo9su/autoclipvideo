"""Publish merged video to Douyin creator platform."""
import http.cookiejar
import json
import logging
import math
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
COOKIE_FILE = os.path.expanduser("~/.douyin_upload_cookies.txt")
CHUNK_SIZE = 5 * 1024 * 1024  # 5 MB chunks

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


def cookie_file_exists() -> bool:
    return os.path.exists(COOKIE_FILE)


def _load_cookies() -> dict:
    jar = http.cookiejar.MozillaCookieJar(COOKIE_FILE)
    jar.load(ignore_discard=True, ignore_expires=True)
    return {c.name: c.value for c in jar}


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


async def _set_publish_status(group_id: int, status: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE clip_groups SET publish_status = ? WHERE id = ?", (status, group_id)
        )
        await db.commit()


async def upload_to_douyin(
    group_id: int, video_path: str, title: str, caption: str, hashtags: list
) -> Optional[str]:
    """Upload video to Douyin creator platform. Returns aweme_id on success."""
    if not os.path.exists(COOKIE_FILE):
        logger.error(f"Cookie file not found: {COOKIE_FILE}")
        await _set_publish_status(group_id, -1)
        return None

    try:
        cookies = _load_cookies()
    except Exception as e:
        logger.error(f"Failed to load cookies: {e}")
        await _set_publish_status(group_id, -1)
        return None

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "https://creator.douyin.com/",
        "Origin": "https://creator.douyin.com",
    }

    try:
        async with httpx.AsyncClient(cookies=cookies, headers=headers, timeout=60.0) as client:
            # Step 1: Init upload
            file_size = os.path.getsize(video_path)
            logger.info(f"Group {group_id}: init upload, size={file_size / 1024 / 1024:.1f} MB")
            init_resp = await client.post(
                "https://creator.douyin.com/aweme/v1/web/publish/video/init/",
                json={"video_info": {"video_size": file_size}},
            )
            if init_resp.status_code != 200:
                logger.error(f"Upload init failed {init_resp.status_code}: {init_resp.text[:300]}")
                await _set_publish_status(group_id, -1)
                return None

            init_data = init_resp.json()
            upload_url = init_data.get("upload_url")
            video_id = init_data.get("video_id")
            if not upload_url or not video_id:
                logger.error(f"Missing upload_url/video_id: {init_data}")
                await _set_publish_status(group_id, -1)
                return None

            # Step 2: Chunked upload
            total_chunks = math.ceil(file_size / CHUNK_SIZE)
            logger.info(f"Group {group_id}: uploading {total_chunks} chunk(s)")
            with open(video_path, "rb") as f:
                for i in range(total_chunks):
                    chunk = f.read(CHUNK_SIZE)
                    start = i * CHUNK_SIZE
                    end = start + len(chunk) - 1
                    chunk_resp = await client.put(
                        upload_url,
                        content=chunk,
                        headers={
                            "Content-Type": "video/mp4",
                            "Content-Range": f"bytes {start}-{end}/{file_size}",
                        },
                        timeout=120.0,
                    )
                    if chunk_resp.status_code not in (200, 206, 308):
                        logger.error(f"Chunk {i} failed: {chunk_resp.status_code}")
                        await _set_publish_status(group_id, -1)
                        return None
                    logger.info(f"Group {group_id}: chunk {i + 1}/{total_chunks} ok")

            # Step 3: Publish post
            text_extra = caption + " " + " ".join(f"#{tag}" for tag in hashtags)
            logger.info(f"Group {group_id}: publishing post")
            pub_resp = await client.post(
                "https://creator.douyin.com/aweme/v1/web/publish/video/",
                json={
                    "video_id": video_id,
                    "title": title[:20],
                    "aweme_info": {
                        "desc": text_extra[:2200],
                        "video_id": video_id,
                        "poi_location": None,
                        "is_draft": 0,
                    },
                },
            )
            if pub_resp.status_code != 200:
                logger.error(f"Publish failed {pub_resp.status_code}: {pub_resp.text[:300]}")
                await _set_publish_status(group_id, -1)
                return None

            pub_data = pub_resp.json()
            aweme_id = pub_data.get("aweme_id") or (pub_data.get("data") or {}).get("aweme_id")
            if not aweme_id:
                logger.error(f"No aweme_id in publish response: {pub_data}")
                await _set_publish_status(group_id, -1)
                return None

            published_url = f"https://www.douyin.com/video/{aweme_id}"
            logger.info(f"Group {group_id} published: {published_url}")
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    """UPDATE clip_groups SET
                       publish_status = 3, published_url = ?, published_at = datetime('now')
                       WHERE id = ?""",
                    (published_url, group_id),
                )
                await db.commit()
            return aweme_id

    except Exception as e:
        logger.error(f"Upload failed for group {group_id}: {e}")
        await _set_publish_status(group_id, -1)
        return None
