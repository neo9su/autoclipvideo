"""
CapCut draft generator for quality comparison with the NVENC pipeline.

Creates a CapCut project on the GPU server with the same source segments
selected by the main editor, referencing the raw recording MP4s.
The user edits/exports in CapCut; results are compared via ffprobe metrics.
"""
import json
import logging
import os
from typing import Optional

import aiohttp
import aiosqlite
import httpx

from db import DB_PATH
from editor import (
    RECORDINGS_DIR,
    _merge_short_segs,
    parse_srt,
    score_and_tag,
    select_clips,
)

logger = logging.getLogger(__name__)

_GPU_SERVICE_URL = os.environ.get("GPU_SERVICE_URL", "http://10.190.0.203:8877")


async def create_capcut_draft(group_id: int) -> Optional[str]:
    """
    Re-runs segment selection for every transcribed recording in the group,
    sends the result to the GPU service to create a CapCut draft.
    Returns the draft_id on success, None on failure.
    """
    async with aiosqlite.connect(DB_PATH, timeout=60) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT r.id, r.filename, g.label
               FROM recordings r
               JOIN clip_groups g ON r.group_id = g.id
               WHERE r.group_id = ? AND r.transcribed = 2
               ORDER BY r.start_time ASC""",
            (group_id,),
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        logger.warning(f"CapCut draft: no transcribed recordings for group {group_id}")
        return None

    label = rows[0]["label"]
    recording_data = []
    for rec in rows:
        srt_path = os.path.join(
            RECORDINGS_DIR, os.path.splitext(rec["filename"])[0] + ".srt"
        )
        if not os.path.exists(srt_path):
            logger.warning(f"CapCut draft: SRT missing for {rec['filename']}")
            continue
        segs = parse_srt(srt_path)
        if not segs:
            continue
        segs = _merge_short_segs(segs)
        for seg in segs:
            score_and_tag(seg)
        selected = select_clips(segs)
        if not selected:
            continue
        recording_data.append({
            "mp4_filename": rec["filename"],
            "segments": [{"start": s.start, "end": s.end} for s in selected],
        })

    if not recording_data:
        logger.warning(f"CapCut draft: no valid segments for group {group_id}")
        return None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{_GPU_SERVICE_URL}/capcut/drafts",
                json={"group_id": group_id, "label": label, "recordings": recording_data},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                _cc_status = resp.status
                _cc_body = await resp.json() if _cc_status == 201 else None
                _cc_text = await resp.text() if _cc_body is None else ""
        if _cc_status != 201:
            logger.error(f"GPU capcut draft error {_cc_status}: {_cc_text[:200]}")
            return None
        data = _cc_body
        draft_id = data["draft_id"]

        async with aiosqlite.connect(DB_PATH, timeout=60) as db:
            await db.execute(
                "UPDATE clip_groups SET capcut_status='draft_ready', capcut_draft_id=? WHERE id=?",
                (draft_id, group_id),
            )
            await db.commit()

        logger.info(f"CapCut draft {draft_id} created for group {group_id}")
        return draft_id

    except Exception as e:
        logger.error(f"CapCut draft creation failed for group {group_id}: {e}")
        return None


async def run_capcut_compare(group_id: int) -> Optional[dict]:
    """
    Asks the GPU service to run ffprobe comparison between the CapCut export
    and our NVENC merged output.  Updates DB with result JSON.
    Returns the comparison dict or None on failure.
    """
    async with aiosqlite.connect(DB_PATH, timeout=60) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT capcut_draft_id, merged_filename FROM clip_groups WHERE id=?",
            (group_id,),
        ) as cur:
            row = await cur.fetchone()

    if not row or not row["capcut_draft_id"]:
        logger.warning(f"CapCut compare: no draft_id for group {group_id}")
        return None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{_GPU_SERVICE_URL}/capcut/drafts/{row['capcut_draft_id']}/compare",
                json={
                    "group_id": group_id,
                    "merged_filename": row["merged_filename"] or "",
                },
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                _cmp_status = resp.status
                _cmp_body = await resp.json() if _cmp_status == 200 else None
                _cmp_text = await resp.text() if _cmp_body is None else ""
        if _cmp_status != 200:
            logger.error(f"GPU capcut compare error {_cmp_status}: {_cmp_text[:200]}")
            return None

        result = _cmp_body
        async with aiosqlite.connect(DB_PATH, timeout=60) as db:
            await db.execute(
                "UPDATE clip_groups SET capcut_status='compared', compare_result=? WHERE id=?",
                (json.dumps(result, ensure_ascii=False), group_id),
            )
            await db.commit()

        return result

    except Exception as e:
        logger.error(f"CapCut compare failed for group {group_id}: {e}")
        return None
