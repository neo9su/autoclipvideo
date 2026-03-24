"""
Segment merger: merge small recording segments before transcription.

Files < SMALL_THRESHOLD (50 MB) are merged with consecutive adjacent segments
from the same room until the combined file approaches MERGE_TARGET (150 MB).

Merge is triggered when:
  - Combined size of the consecutive group >= SMALL_THRESHOLD, OR
  - The room is no longer actively recording (stream ended)

While the room is still recording and the group is too small, upload is deferred
(returns None) so the poll loop can retry later.
"""

import asyncio
import logging
import os
from typing import Optional

import aiosqlite

from db import DB_PATH

logger = logging.getLogger(__name__)

SMALL_THRESHOLD = 50 * 1024 * 1024   # files smaller than this get merged
MERGE_TARGET    = 150 * 1024 * 1024  # target size for merged file

RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), "..", "recordings")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _is_room_still_recording(room_id: int) -> bool:
    """Return True if there is an in-progress segment (end_time IS NULL) for room."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM recordings WHERE room_id=? AND end_time IS NULL AND local_deleted=0",
            (room_id,),
        ) as cur:
            count = (await cur.fetchone())[0]
    return count > 0


async def _get_pending_unsynced(room_id: int) -> list:
    """Return finished, unsynced, non-deleted segments for room ordered by segment_index."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT id, filename, segment_index, size_bytes, start_time
               FROM recordings
               WHERE room_id=? AND synced=0 AND transcribed=0
                 AND local_deleted=0 AND end_time IS NOT NULL AND size_bytes IS NOT NULL
               ORDER BY segment_index, start_time""",
            (room_id,),
        ) as cur:
            return await cur.fetchall()


def _consecutive_group_for(segments: list, target_id: int) -> list:
    """
    Find the run of consecutive-by-segment_index rows that contains target_id.
    Two rows are consecutive if their segment_index values differ by exactly 1.
    Returns the group, or a list containing only the target row if not found in any group.
    """
    if not segments:
        return []

    groups: list[list] = []
    current: list = [segments[0]]
    for seg in segments[1:]:
        if seg["segment_index"] == current[-1]["segment_index"] + 1:
            current.append(seg)
        else:
            groups.append(current)
            current = [seg]
    groups.append(current)

    for group in groups:
        if any(s["id"] == target_id for s in group):
            return group

    # target_id not found in any group (shouldn't happen, but safe fallback)
    for seg in segments:
        if seg["id"] == target_id:
            return [seg]
    return []


async def _ffmpeg_concat(file_paths: list[str], output_path: str) -> bool:
    """Concatenate MP4 files with ffmpeg concat demuxer (stream copy, lossless)."""
    list_file = output_path + ".concat.txt"
    try:
        with open(list_file, "w", encoding="utf-8") as f:
            for p in file_paths:
                escaped = p.replace("\\", "/").replace("'", "\\'")
                f.write(f"file '{escaped}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_file,
            "-c", "copy",
            output_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error(f"ffmpeg concat failed (rc={proc.returncode}): {stderr.decode()[-500:]}")
            return False
        return True
    finally:
        try:
            os.unlink(list_file)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def maybe_merge_before_upload(
    room_id: int, recording_id: int
) -> Optional[tuple[str, int]]:
    """
    Decide whether to merge segments before uploading to the GPU service.

    Returns:
        (upload_filepath, primary_recording_id)
            The file to upload and the DB record id to mark as synced/transcribed.
        None
            The file is small and we should wait for more segments to arrive
            (room still recording, not enough data accumulated yet).
    """
    # Load the target recording
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, filename, segment_index, size_bytes, local_deleted, synced FROM recordings WHERE id=?",
            (recording_id,),
        ) as cur:
            rec = await cur.fetchone()

    if not rec:
        return None

    # Already absorbed into a merged file, or already uploaded — skip
    if rec["local_deleted"] or rec["synced"]:
        return None

    filepath = os.path.join(RECORDINGS_DIR, rec["filename"])
    if not os.path.exists(filepath):
        return None

    size = rec["size_bytes"] or os.path.getsize(filepath)

    # Large file — no merge needed
    if size >= SMALL_THRESHOLD:
        return (filepath, recording_id)

    # Small file — find consecutive group in pending unsynced segments
    pending = await _get_pending_unsynced(room_id)
    group = _consecutive_group_for(pending, recording_id)

    # Collect group members that exist on disk
    valid: list[tuple] = []  # (row, filepath, size)
    for seg in group:
        p = os.path.join(RECORDINGS_DIR, seg["filename"])
        if os.path.exists(p):
            sz = seg["size_bytes"] or os.path.getsize(p)
            valid.append((seg, p, sz))

    if not valid:
        return (filepath, recording_id)

    total_size = sum(sz for _, _, sz in valid)
    still_recording = await _is_room_still_recording(room_id)

    # Not enough data and room still active — defer
    if total_size < SMALL_THRESHOLD and still_recording:
        logger.info(
            f"Room {room_id}: small group {len(valid)} segs "
            f"{total_size // 1024 // 1024}MB < {SMALL_THRESHOLD // 1024 // 1024}MB, "
            "waiting for more segments"
        )
        return None

    # Only one file — upload as-is (can't merge alone)
    if len(valid) == 1:
        return (filepath, recording_id)

    # Select segments up to MERGE_TARGET
    selected: list[tuple] = []
    selected_size = 0
    for seg, p, sz in valid:
        if selected_size >= MERGE_TARGET:
            break
        selected.append((seg, p, sz))
        selected_size += sz

    if len(selected) == 1:
        return (filepath, recording_id)

    # Build merged filename from first→last segment indices
    first_seg = selected[0][0]
    last_seg  = selected[-1][0]
    merged_filename = (
        f"merged_{room_id}"
        f"_{first_seg['segment_index']:03d}"
        f"_{last_seg['segment_index']:03d}.mp4"
    )
    merged_path = os.path.join(RECORDINGS_DIR, merged_filename)

    file_paths = [p for _, p, _ in selected]
    logger.info(
        f"Room {room_id}: merging {len(selected)} segments "
        f"({selected_size // 1024 // 1024}MB) → {merged_filename}"
    )

    ok = await _ffmpeg_concat(file_paths, merged_path)
    if not ok:
        # ffmpeg failed — fall back to uploading the original file
        logger.warning(f"Room {room_id}: merge failed, falling back to original {rec['filename']}")
        return (filepath, recording_id)

    merged_size = os.path.getsize(merged_path)

    # Update DB atomically:
    #   - First segment record gets the merged filename
    #   - Remaining segments get local_deleted=1 (their content is now in the merged file)
    first_id  = first_seg["id"]
    other_ids = [seg["id"] for seg, _, _ in selected[1:]]

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE recordings SET filename=?, size_bytes=? WHERE id=?",
            (merged_filename, merged_size, first_id),
        )
        for oid in other_ids:
            await db.execute(
                "UPDATE recordings SET local_deleted=1 WHERE id=?",
                (oid,),
            )
        await db.commit()

    logger.info(
        f"Room {room_id}: merged → {merged_filename} "
        f"({merged_size // 1024 // 1024}MB, absorbed ids={other_ids})"
    )
    return (merged_path, first_id)
