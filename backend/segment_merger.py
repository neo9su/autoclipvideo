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
import time
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from db import DB_PATH

logger = logging.getLogger(__name__)

SMALL_THRESHOLD  = 50  * 1024 * 1024  # files smaller than this get merged
STALE_WAIT_SECS  = 600                # force-upload small files after waiting this long
MERGE_TARGET     = 150 * 1024 * 1024  # target size for merged file
MERGE_MAX        = 200 * 1024 * 1024  # hard cap: never produce a merged file larger than this
SPLIT_THRESHOLD  = 200 * 1024 * 1024  # standalone files larger than this get split before upload
SPLIT_CHUNK_SIZE = 150 * 1024 * 1024  # target chunk size when splitting large files

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


async def _ffprobe_duration(filepath: str) -> Optional[float]:
    """Return video duration in seconds using ffprobe, or None on failure."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", filepath,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return None
    try:
        import json
        info = json.loads(stdout)
        return float(info["format"]["duration"])
    except Exception:
        return None


async def _ffmpeg_split_file(
    filepath: str, file_size: int, room_id: int, recording_id: int
) -> Optional[list[tuple[str, int]]]:
    """
    Split a large MP4 file into ~SPLIT_CHUNK_SIZE chunks using stream-copy.

    Returns list of (chunk_filepath, chunk_size_bytes) pairs (including the first
    chunk, which reuses the original path slot), or None on failure.
    The caller is responsible for updating the DB and deleting the original file.
    """
    duration = await _ffprobe_duration(filepath)
    if not duration or duration <= 0:
        logger.warning(f"Could not determine duration for {filepath}, skipping split")
        return None

    bytes_per_sec = file_size / duration
    chunk_duration = SPLIT_CHUNK_SIZE / bytes_per_sec
    n_chunks = max(2, int(os.path.getsize(filepath) / SPLIT_CHUNK_SIZE) + 1)

    stem, ext = os.path.splitext(os.path.basename(filepath))
    dir_path = os.path.dirname(filepath)

    chunks: list[tuple[str, int]] = []
    for i in range(n_chunks):
        ss = i * chunk_duration
        if ss >= duration:
            break
        chunk_filename = f"{stem}_chunk{i:03d}{ext}"
        chunk_path = os.path.join(dir_path, chunk_filename)
        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{ss:.3f}", "-i", filepath,
            "-t", f"{chunk_duration:.3f}",
            "-c", "copy",
            chunk_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0 or not os.path.exists(chunk_path):
            logger.error(
                f"Split chunk {i} failed for {filepath}: {stderr.decode()[-300:]}"
            )
            # Clean up any chunks written so far
            for cp, _ in chunks:
                try:
                    os.unlink(cp)
                except Exception:
                    pass
            return None
        chunk_size = os.path.getsize(chunk_path)
        chunks.append((chunk_path, chunk_size))
        logger.info(
            f"Split chunk {i+1}/{n_chunks}: {chunk_filename} ({chunk_size // 1024 // 1024}MB)"
        )

    return chunks if len(chunks) >= 2 else None


async def _split_and_register(
    filepath: str, file_size: int, room_id: int, recording_id: int
) -> Optional[tuple[str, int]]:
    """
    Split `filepath` into SPLIT_CHUNK_SIZE chunks, register extra chunks as new
    DB rows (inheriting room_id), update the original row to point to chunk 0,
    and delete the original large file.

    Returns (chunk0_path, recording_id) for the first chunk, or None on failure.
    """
    chunks = await _ffmpeg_split_file(filepath, file_size, room_id, recording_id)
    if not chunks:
        return None

    chunk0_path, chunk0_size = chunks[0]

    async with aiosqlite.connect(DB_PATH) as db:
        # Find original recording to get its segment_index
        async with db.execute(
            "SELECT segment_index FROM recordings WHERE id=?", (recording_id,)
        ) as cur:
            row = await cur.fetchone()
        base_index = row[0] if row else 0

        # Update original row → chunk 0
        chunk0_filename = os.path.basename(chunk0_path)
        await db.execute(
            "UPDATE recordings SET filename=?, size_bytes=? WHERE id=?",
            (chunk0_filename, chunk0_size, recording_id),
        )

        # Insert new rows for chunks 1..N
        for i, (cp, csz) in enumerate(chunks[1:], start=1):
            await db.execute(
                """INSERT INTO recordings
                   (room_id, filename, size_bytes, synced, transcribed, local_deleted, segment_index)
                   VALUES (?, ?, ?, 0, 0, 0, ?)""",
                (room_id, os.path.basename(cp), csz, base_index + i),
            )

        await db.commit()

    # Delete the original large file
    try:
        os.unlink(filepath)
    except Exception as e:
        logger.warning(f"Could not delete original file {filepath}: {e}")

    logger.info(
        f"Split {os.path.basename(filepath)} ({file_size // 1024 // 1024}MB) "
        f"→ {len(chunks)} chunks, registered in DB"
    )
    return (chunk0_path, recording_id)


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

    # Large file — no merge needed, but split if it exceeds the upload cap
    if size >= SMALL_THRESHOLD:
        if size > SPLIT_THRESHOLD:
            logger.info(
                f"Recording {recording_id}: file {rec['filename']} is "
                f"{size // 1024 // 1024}MB > {SPLIT_THRESHOLD // 1024 // 1024}MB, splitting"
            )
            result = await _split_and_register(filepath, size, room_id, recording_id)
            if result:
                return result
            # Split failed — fall through and upload as-is
            logger.warning(f"Split failed for {rec['filename']}, uploading original")
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

    # Not enough data and room still active — defer, but only up to STALE_WAIT_SECS
    if total_size < SMALL_THRESHOLD and still_recording:
        # Check how long the oldest segment in the group has been waiting
        oldest_start = min(
            (seg["start_time"] for seg, _, _ in valid if seg["start_time"]),
            default=None,
        )
        wait_secs = 0
        if oldest_start:
            try:
                dt = datetime.fromisoformat(oldest_start.replace(" ", "T"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                wait_secs = int(time.time() - dt.timestamp())
            except Exception:
                pass
        if wait_secs < STALE_WAIT_SECS:
            logger.info(
                f"Room {room_id}: small group {len(valid)} segs "
                f"{total_size // 1024 // 1024}MB < {SMALL_THRESHOLD // 1024 // 1024}MB, "
                f"waiting for more segments (waited {wait_secs}s / {STALE_WAIT_SECS}s)"
            )
            return None
        logger.info(
            f"Room {room_id}: small group waited {wait_secs}s >= {STALE_WAIT_SECS}s, "
            "force-uploading despite active recording"
        )

    # Only one file — upload as-is (can't merge alone)
    if len(valid) == 1:
        return (filepath, recording_id)

    # Select segments up to MERGE_TARGET, but never let the total exceed MERGE_MAX
    selected: list[tuple] = []
    selected_size = 0
    for seg, p, sz in valid:
        if selected_size + sz > MERGE_MAX:
            break  # adding this file would push merged size over 200 MB
        if selected_size >= MERGE_TARGET:
            break  # already at target size
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
