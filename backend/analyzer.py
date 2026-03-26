"""
Semantic analysis of recording SRT via Bedrock LLM.
Extracts wig model/color and assigns recording to a clip group.
"""
import asyncio
import json
import logging
import os
import re
from datetime import datetime
from typing import Optional

import aiosqlite
import httpx

from db import DB_PATH

logger = logging.getLogger(__name__)

BEDROCK_URL = "https://bedrock-runtime.us-east-1.amazonaws.com"
BEDROCK_MODEL = os.environ.get("BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-6")
BEDROCK_TOKEN = os.environ.get("AWS_BEARER_TOKEN_BEDROCK", "")
RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), "..", "recordings")

_PROMPT = """你是假发直播间内容分析专家。分析以下直播字幕，提取产品信息。

字幕内容：
{text}

请以JSON格式返回（只返回JSON，不含其他内容）：
{{
  "wig_model": "主要介绍的假发款式名称（如：大波浪卷发、蓬松波波头、丝滑直发等），未提及返回null",
  "wig_color": "主要颜色（如：自然黑、深棕、浅棕、奶茶色、金色等），未提及返回null",
  "session_label": "本段核心内容一句话（10字以内）",
  "has_tryon": true或false（是否有试戴/变身展示）,
  "has_promotion": true或false（是否有促销/限时活动）
}}"""


async def _call_bedrock(text: str) -> Optional[dict]:
    if not BEDROCK_TOKEN:
        logger.error("AWS_BEARER_TOKEN_BEDROCK not set, skipping analysis")
        return None

    prompt = _PROMPT.format(text=text)
    payload = {
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": {"maxTokens": 400, "temperature": 0},
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


def _srt_to_text(srt_path: str, max_chars: int = 4000) -> str:
    """Extract plain text from SRT, truncated to max_chars."""
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
        if len(text) > max_chars:
            # Sample evenly to preserve coverage
            step = len(text) // max_chars
            text = text[::max(1, step)][:max_chars]
        return text
    except Exception as e:
        logger.error(f"SRT read error {srt_path}: {e}")
        return ""


async def _get_or_create_group(room_id: int, wig_model: Optional[str], wig_color: Optional[str]) -> int:
    label_parts = [p for p in [wig_model, wig_color] if p]
    label = " ".join(label_parts) if label_parts else "未分类"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT id FROM clip_groups
               WHERE room_id = ? AND (wig_model IS ? OR (wig_model IS NULL AND ? IS NULL))
                                 AND (wig_color IS ? OR (wig_color IS NULL AND ? IS NULL))""",
            (room_id, wig_model, wig_model, wig_color, wig_color),
        ) as cur:
            row = await cur.fetchone()
        if row:
            return row["id"]
        cur = await db.execute(
            "INSERT INTO clip_groups (room_id, wig_model, wig_color, label) VALUES (?, ?, ?, ?)",
            (room_id, wig_model, wig_color, label),
        )
        await db.commit()
        return cur.lastrowid


async def analyze_recording(recording_id: int, filename: str, room_id: int):
    """Analyze SRT with LLM and assign recording to a clip group."""
    srt_filename = os.path.splitext(filename)[0] + ".srt"
    srt_path = os.path.join(RECORDINGS_DIR, srt_filename)

    if not os.path.exists(srt_path):
        logger.warning(f"SRT missing for analysis: {srt_path}")
        return

    text = _srt_to_text(srt_path)
    if not text:
        return

    result = await _call_bedrock(text)
    if not result:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE recordings SET analyzed = -1 WHERE id = ?", (recording_id,))
            await db.commit()
        return

    wig_model     = result.get("wig_model")
    wig_color     = result.get("wig_color")
    session_label = result.get("session_label") or ""
    has_tryon     = 1 if result.get("has_tryon") else 0
    has_promotion = 1 if result.get("has_promotion") else 0

    group_id = await _get_or_create_group(room_id, wig_model, wig_color)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE recordings SET
               analyzed = 1, wig_model = ?, wig_color = ?,
               session_label = ?, has_tryon = ?, has_promotion = ?, group_id = ?
               WHERE id = ?""",
            (wig_model, wig_color, session_label, has_tryon, has_promotion, group_id, recording_id),
        )
        await db.commit()

    logger.info(f"Recording {recording_id} → group {group_id} [{wig_model} / {wig_color}]")


# ── Group merge ───────────────────────────────────────────────────────────────

async def merge_group(group_id: int) -> Optional[str]:
    """Concatenate all ready clips in a group into one MP4. Returns output filename."""
    import tempfile

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT r.clip_filename, g.wig_model, g.wig_color
               FROM recordings r
               JOIN clip_groups g ON r.group_id = g.id
               WHERE r.group_id = ? AND r.clipped = 2 AND r.clip_filename IS NOT NULL
               ORDER BY r.start_time ASC""",
            (group_id,),
        ) as cur:
            rows = await cur.fetchall()
        await db.execute(
            "UPDATE clip_groups SET merge_status = 1 WHERE id = ?", (group_id,)
        )
        await db.commit()

    if not rows:
        logger.warning(f"No ready clips for group {group_id}")
        return None

    parts = [os.path.join(RECORDINGS_DIR, r["clip_filename"]) for r in rows]
    parts = [p for p in parts if os.path.exists(p)]
    if not parts:
        logger.error(f"All clip files missing for group {group_id}")
        return None

    g = rows[0]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_slug = (g["wig_model"] or "未知款").replace(" ", "_")
    color_slug = (g["wig_color"] or "未知色").replace(" ", "_")
    out_filename = f"merged_{group_id}_{model_slug}_{color_slug}_{ts}.mp4"
    out_path = os.path.join(RECORDINGS_DIR, out_filename)

    # Write concat list
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        for p in parts:
            f.write(f"file '{p}'\n")
        list_file = f.name

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-c", "copy",
        out_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    os.unlink(list_file)

    if proc.returncode == 0 and os.path.exists(out_path):
        size_mb = os.path.getsize(out_path) / 1024 / 1024
        logger.info(f"Group {group_id} merged: {out_filename} ({size_mb:.1f} MB)")
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """UPDATE clip_groups SET
                   merge_status = 2, merged_filename = ?, merged_at = datetime('now')
                   WHERE id = ?""",
                (out_filename, group_id),
            )
            await db.commit()
        return out_filename
    else:
        err_msg = stderr.decode(errors="replace")[-400:].strip()
        logger.error(f"Merge failed for group {group_id}: {err_msg}")
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE clip_groups SET merge_status = -1, merge_error = ? WHERE id = ?",
                (err_msg or "未知错误", group_id),
            )
            await db.commit()
        return None
