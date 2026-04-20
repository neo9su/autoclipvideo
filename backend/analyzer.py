"""
Semantic analysis of recording SRT via Bedrock LLM.
Extracts wig model/color and assigns recording to a clip group.
"""
import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Optional

import aiohttp
import aiosqlite
import httpx

from db import DB_PATH, aio_connect

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

    for attempt in range(1, 4):
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
            if resp.status_code == 200:
                raw = resp.json()["output"]["message"]["content"][0]["text"]
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                if m:
                    return json.loads(m.group())
                logger.error(f"No JSON in Bedrock response: {raw[:200]}")
                return None
            elif resp.status_code in (429, 500, 502, 503) and attempt < 3:
                logger.warning(f"Bedrock {resp.status_code}, retrying (attempt {attempt}/3)...")
            else:
                logger.error(f"Bedrock error {resp.status_code}: {resp.text[:300]}")
                return None
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            if attempt < 3:
                logger.warning(f"Bedrock transient error ({e}), retrying (attempt {attempt}/3)...")
            else:
                logger.error(f"Bedrock call failed after 3 attempts: {e}")
                return None
        except Exception as e:
            logger.error(f"Bedrock call failed: {e}")
            return None

        await asyncio.sleep(2 ** attempt)  # 2s, 4s backoff

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
    async with aio_connect() as db:
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
            "INSERT INTO clip_groups (room_id, wig_model, wig_color, label, editing_mode) VALUES (?, ?, ?, ?, 'director')",
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
        async with aio_connect() as db:
            await db.execute("UPDATE recordings SET analyzed = -1 WHERE id = ?", (recording_id,))
            await db.commit()
        return

    wig_model     = result.get("wig_model")
    wig_color     = result.get("wig_color")
    session_label = result.get("session_label") or ""
    has_tryon     = 1 if result.get("has_tryon") else 0
    has_promotion = 1 if result.get("has_promotion") else 0

    group_id = await _get_or_create_group(room_id, wig_model, wig_color)

    async with aio_connect() as db:
        await db.execute(
            """UPDATE recordings SET
               analyzed = 1, wig_model = ?, wig_color = ?,
               session_label = ?, has_tryon = ?, has_promotion = ?, group_id = ?
               WHERE id = ?""",
            (wig_model, wig_color, session_label, has_tryon, has_promotion, group_id, recording_id),
        )
        await db.commit()

    logger.info(f"Recording {recording_id} → group {group_id} [{wig_model} / {wig_color}]")

    # Trigger auto-merge check AFTER group_id is committed, avoiding the race condition
    # where _maybe_auto_merge (fired from _do_edit) runs before this function sets group_id.
    try:
        from transcribe import _maybe_auto_merge
        await _maybe_auto_merge(recording_id)
    except Exception as e:
        logger.warning(f"Post-analyze auto-merge check failed for recording {recording_id}: {e}")


# ── Group merge ───────────────────────────────────────────────────────────────

_GPU_SERVICE_URL = os.environ.get("GPU_SERVICE_URL", "http://10.190.0.203:8877")


async def _gpu_concat(gpu_url: str, job_ids: list, out_path: str, group_id: int) -> Optional[str]:
    """Submit concat job to GPU server (stream-copy, requires in-memory clip job IDs)."""
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{gpu_url}/concat-jobs", json={"clip_job_ids": job_ids},
                                timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 201:
                _err = await resp.text()
                raise RuntimeError(f"concat-jobs POST failed: {resp.status} {_err[:200]}")
            concat_job_id = (await resp.json())["job_id"]

    logger.info(f"Group {group_id}: GPU concat job {concat_job_id} for {len(job_ids)} clips")

    deadline = time.time() + 600
    while time.time() < deadline:
        await asyncio.sleep(5)
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{gpu_url}/concat-jobs/{concat_job_id}",
                                   timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"concat-jobs status failed: {resp.status}")
                data = await resp.json()
        if data["status"] == "done":
            break
        elif data["status"] == "error":
            raise RuntimeError(f"GPU concat error: {data.get('error')}")
    else:
        raise RuntimeError("GPU concat timed out after 10 minutes")

    out_filename = os.path.basename(out_path)
    logger.info(f"Group {group_id}: downloading GPU concat {concat_job_id}")
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{gpu_url}/concat-jobs/{concat_job_id}/mp4",
                               timeout=aiohttp.ClientTimeout(total=300)) as resp:
            if resp.status != 200:
                raise RuntimeError(f"concat MP4 download failed: {resp.status}")
            with open(out_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(65536):
                    f.write(chunk)

    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError("Downloaded merged file is empty")

    size_mb = os.path.getsize(out_path) / 1024 / 1024
    logger.info(f"Group {group_id}: GPU concat done → {out_filename} ({size_mb:.1f} MB)")

    async with aio_connect() as db:
        await db.execute(
            """UPDATE clip_groups SET
               merge_status = 2, classic_status = 2, merged_filename = ?, merged_at = datetime('now')
               WHERE id = ?""",
            (out_filename, group_id),
        )
        await db.commit()
    return out_filename


async def _gpu_classic_concat(gpu_url: str, clip_paths: list, out_path: str, group_id: int) -> Optional[str]:
    """Upload pre-processed clip files to GPU, NVENC-merge them, download result.

    This path is always available regardless of GPU service restarts because
    it sends the actual clip files rather than relying on in-memory job IDs.
    """
    import httpx

    logger.info(f"Group {group_id}: uploading {len(clip_paths)} clips to GPU for NVENC classic-concat")

    # Upload all clip files as multipart
    files = []
    try:
        for p in clip_paths:
            files.append(("files", (os.path.basename(p), open(p, "rb"), "video/mp4")))

        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(f"{gpu_url}/classic-concat-jobs", files=files)
        if resp.status_code != 201:
            raise RuntimeError(f"classic-concat-jobs POST failed: {resp.status_code} {resp.text[:200]}")
        job_id = resp.json()["job_id"]
    finally:
        for _, (_, fobj, _) in files:
            try:
                fobj.close()
            except Exception:
                pass

    logger.info(f"Group {group_id}: GPU classic-concat job {job_id}")

    # Poll for completion (20 min max; NVENC per-clip encoding takes time)
    deadline = time.time() + 1200
    async with httpx.AsyncClient(timeout=15.0) as client:
        while time.time() < deadline:
            await asyncio.sleep(8)
            try:
                resp = await client.get(f"{gpu_url}/classic-concat-jobs/{job_id}")
                data = resp.json()
            except Exception as e:
                logger.warning(f"Group {group_id}: GPU classic-concat poll error: {e}")
                continue
            if data["status"] == "done":
                break
            elif data["status"] == "error":
                raise RuntimeError(f"GPU classic-concat error: {data.get('error')}")
        else:
            raise RuntimeError("GPU classic-concat timed out after 20 minutes")

    # Download result
    out_filename = os.path.basename(out_path)
    logger.info(f"Group {group_id}: downloading GPU classic-concat {job_id}")
    async with httpx.AsyncClient(timeout=300.0) as client:
        async with client.stream("GET", f"{gpu_url}/classic-concat-jobs/{job_id}/mp4") as resp:
            if resp.status_code != 200:
                raise RuntimeError(f"classic-concat MP4 download failed: {resp.status_code}")
            with open(out_path, "wb") as f:
                async for chunk in resp.aiter_bytes(65536):
                    f.write(chunk)

    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError("Downloaded classic-concat file is empty")

    size_mb = os.path.getsize(out_path) / 1024 / 1024
    logger.info(f"Group {group_id}: GPU classic-concat done → {out_filename} ({size_mb:.1f} MB)")

    async with aio_connect() as db:
        await db.execute(
            """UPDATE clip_groups SET
               merge_status = 2, classic_status = 2, merged_filename = ?, merged_at = datetime('now')
               WHERE id = ?""",
            (out_filename, group_id),
        )
        await db.commit()
    return out_filename


async def merge_group(group_id: int) -> Optional[str]:
    """Concatenate all ready clips in a group into one MP4. Returns output filename."""
    import tempfile
    from collections import defaultdict

    async with aio_connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT r.id AS recording_id, r.clip_filename, g.wig_model, g.wig_color
               FROM recordings r
               JOIN clip_groups g ON r.group_id = g.id
               WHERE r.group_id = ? AND r.clipped = 2 AND r.clip_filename IS NOT NULL
               ORDER BY r.start_time ASC""",
            (group_id,),
        ) as cur:
            rows = await cur.fetchall()
        await db.execute(
            "UPDATE clip_groups SET merge_status = 1, classic_status = 1 WHERE id = ?", (group_id,)
        )
        await db.commit()

    if not rows:
        logger.warning(f"No ready clips for group {group_id}")
        async with aio_connect() as db:
            await db.execute(
                "UPDATE clip_groups SET classic_status = -1 WHERE id = ?", (group_id,)
            )
            await db.commit()
        return None

    g = rows[0]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_slug = (g["wig_model"] or "未知款").replace(" ", "_").replace("/", "_").replace("\\", "_")
    color_slug = (g["wig_color"] or "未知色").replace(" ", "_").replace("/", "_").replace("\\", "_")
    out_filename = f"merged_{group_id}_{model_slug}_{color_slug}_{ts}.mp4"
    out_path = os.path.join(RECORDINGS_DIR, out_filename)

    # ── Collect clip job IDs (used by Path 2 stream-copy fallback) ───────────────
    recording_ids = [r["recording_id"] for r in rows]
    placeholders = ",".join("?" * len(recording_ids))
    async with aio_connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"""SELECT recording_id, gpu_clip_job_id FROM recording_clips
                WHERE recording_id IN ({placeholders})
                ORDER BY recording_id, variant_idx""",
            recording_ids,
        ) as cur:
            clip_rows = await cur.fetchall()

    clip_job_map: dict = defaultdict(list)
    for cr in clip_rows:
        if cr["gpu_clip_job_id"]:
            clip_job_map[cr["recording_id"]].append(cr["gpu_clip_job_id"])

    # ── Path 1: GPU classic-concat (upload clips → NVENC re-encode) ─────────────
    # This path works regardless of GPU restarts since we send actual clip files.
    # Falls back to Path 2 (stream-copy on GPU) or Path 3 (local) on failure.
    parts = [os.path.join(RECORDINGS_DIR, r["clip_filename"]) for r in rows]
    parts = [p for p in parts if os.path.exists(p)]
    if not parts:
        logger.error(f"All clip files missing for group {group_id}")
        async with aio_connect() as db:
            await db.execute(
                "UPDATE clip_groups SET merge_status = -1, merge_error = ? WHERE id = ?",
                ("所有剪辑文件不存在", group_id),
            )
            await db.commit()
        return None

    from gpu_state import is_online as _gpu_is_online
    if _gpu_is_online():
        try:
            result = await _gpu_classic_concat(_GPU_SERVICE_URL, parts, out_path, group_id)
            if result:
                return result
        except Exception as e:
            logger.warning(f"GPU classic-concat failed for group {group_id}: {e} — trying stream-copy fallback")

    # ── Path 2: GPU stream-copy concat (requires in-memory clip job IDs) ─────────
    can_gpu = all(clip_job_map.get(rid) for rid in recording_ids)
    if can_gpu:
        ordered_job_ids = []
        for rid in recording_ids:
            ordered_job_ids.extend(clip_job_map[rid])
        try:
            result = await _gpu_concat(_GPU_SERVICE_URL, ordered_job_ids, out_path, group_id)
            if result:
                return result
        except Exception as e:
            logger.warning(f"GPU stream-copy concat failed for group {group_id}: {e} — falling back to local")

    # ── Path 3: local ffmpeg stream-copy concat (last resort) ────────────────────
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
        logger.info(f"Group {group_id} merged (local fallback): {out_filename} ({size_mb:.1f} MB)")
        async with aio_connect() as db:
            await db.execute(
                """UPDATE clip_groups SET
                   merge_status = 2, classic_status = 2, merged_filename = ?, merged_at = datetime('now')
                   WHERE id = ?""",
                (out_filename, group_id),
            )
            await db.commit()
        return out_filename
    else:
        err_msg = stderr.decode(errors="replace")[-400:].strip()
        logger.error(f"Merge failed for group {group_id}: {err_msg}")
        async with aio_connect() as db:
            await db.execute(
                "UPDATE clip_groups SET classic_status = -1, merge_error = ? WHERE id = ?",
                (err_msg or "未知错误", group_id),
            )
            await db.commit()
        return None
