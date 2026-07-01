"""
Segment merger: merge small recording segments before transcription.

Files < SMALL_THRESHOLD (50 MB) are merged with consecutive adjacent segments
from the same room until the combined duration approaches MERGE_TARGET_DUR (15 min).

Merge is triggered when:
  - Combined duration of the consecutive group >= 15 minutes, OR
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

from db import DB_PATH, aio_connect

logger = logging.getLogger(__name__)

# Per-file lock to prevent concurrent split/merge operations on the same file.
# Key: absolute file path, Value: asyncio.Lock
_file_locks: dict[str, asyncio.Lock] = {}
_file_locks_mu = asyncio.Lock()  # protects _file_locks dict itself


async def _get_file_lock(filepath: str) -> asyncio.Lock:
    """Get or create an asyncio.Lock for a given file path."""
    key = os.path.realpath(filepath)
    async with _file_locks_mu:
        if key not in _file_locks:
            _file_locks[key] = asyncio.Lock()
        return _file_locks[key]


async def _release_file_lock(filepath: str):
    """Remove the lock entry to avoid unbounded memory growth."""
    key = os.path.realpath(filepath)
    async with _file_locks_mu:
        _file_locks.pop(key, None)

SMALL_THRESHOLD  = 50  * 1024 * 1024  # files smaller than this get merged
STALE_WAIT_SECS  = 600                # force-upload small files after waiting this long
MERGE_TARGET_DUR = 900                # target duration for merged file: 15 minutes (seconds)
MERGE_MAX_DUR    = 1200               # hard cap: never merge beyond 20 minutes total duration
SPLIT_THRESHOLD  = 200 * 1024 * 1024  # standalone files larger than this get split before upload
SPLIT_CHUNK_SIZE = 150 * 1024 * 1024  # target chunk size when splitting large files

RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), "..", "recordings")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _is_room_still_recording(room_id: int) -> bool:
    """Return True if there is an in-progress segment (end_time IS NULL) for room."""
    async with aio_connect() as db:
        async with db.execute(
            "SELECT COUNT(*) FROM recordings WHERE room_id=? AND end_time IS NULL AND local_deleted=0",
            (room_id,),
        ) as cur:
            count = (await cur.fetchone())[0]
    return count > 0


async def _get_pending_unsynced(room_id: int) -> list:
    """Return finished, unsynced, non-deleted segments for room ordered by segment_index.
    Also computes duration from size_bytes assuming ~1 Mbps bitrate (conservative estimate).
    """
    async with aio_connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT id, filename, segment_index, size_bytes, start_time, end_time
               FROM recordings
               WHERE room_id=? AND synced=0 AND transcribed=0
                 AND local_deleted=0 AND end_time IS NOT NULL AND size_bytes IS NOT NULL
               ORDER BY segment_index, start_time""",
            (room_id,),
        ) as cur:
            rows = await cur.fetchall()
    # Compute approximate duration from start/end times
    # Convert sqlite3.Row to dict so we can add _dur field
    result = []
    for row in rows:
        d = dict(row)
        try:
            if d["start_time"] and d["end_time"]:
                st = d["start_time"].replace(" ", "T")
                et = d["end_time"].replace(" ", "T")
                dt_s = datetime.fromisoformat(st)
                dt_e = datetime.fromisoformat(et)
                d["_dur"] = (dt_e - dt_s).total_seconds()
            else:
                # Fallback: estimate from file size (~1 Mbps for phone recordings)
                sz = d["size_bytes"] or 0
                d["_dur"] = max(0, (sz * 8) / (1_000_000))  # seconds
        except Exception:
            d["_dur"] = 0
        result.append(d)
    return result


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

    # Idempotency check: if chunk000 already exists, another split completed first
    chunk0_candidate = os.path.join(dir_path, f"{stem}_chunk000{ext}")
    if os.path.exists(chunk0_candidate):
        logger.info(f"Split skipped for {filepath}: chunks already exist (chunk000 present)")
        return None

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

    async with aio_connect() as db:
        # Find original recording to get its segment_index, start_time, and end_time
        async with db.execute(
            "SELECT segment_index, start_time, end_time FROM recordings WHERE id=?", (recording_id,)
        ) as cur:
            row = await cur.fetchone()
        base_index = row[0] if row else 0
        start_time = row[1] if row else ""
        end_time   = row[2] if row else ""

        # Update original row → chunk 0
        chunk0_filename = os.path.basename(chunk0_path)
        await db.execute(
            "UPDATE recordings SET filename=?, size_bytes=? WHERE id=?",
            (chunk0_filename, chunk0_size, recording_id),
        )

        # Insert new rows for chunks 1..N (must include end_time so they aren't
        # treated as in-progress recordings by the poll loop's end_time IS NOT NULL check)
        for i, (cp, csz) in enumerate(chunks[1:], start=1):
            await db.execute(
                """INSERT INTO recordings
                   (room_id, filename, size_bytes, synced, transcribed, local_deleted,
                    segment_index, start_time, end_time)
                   VALUES (?, ?, ?, 0, 0, 0, ?, ?, ?)""",
                (room_id, os.path.basename(cp), csz, base_index + i, start_time, end_time),
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
    async with aio_connect() as db:
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
            lock = await _get_file_lock(filepath)
            if lock.locked():
                # Another coroutine is already splitting this file — skip
                logger.debug(
                    f"Recording {recording_id}: split already in progress for {rec['filename']}, skipping"
                )
                return None
            async with lock:
                # Re-check file existence after acquiring lock (another split may have deleted it)
                if not os.path.exists(filepath):
                    logger.info(
                        f"Recording {recording_id}: file {rec['filename']} gone after lock (already split), skipping"
                    )
                    await _release_file_lock(filepath)
                    return None
                logger.info(
                    f"Recording {recording_id}: file {rec['filename']} is "
                    f"{size // 1024 // 1024}MB > {SPLIT_THRESHOLD // 1024 // 1024}MB, splitting"
                )
                result = await _split_and_register(filepath, size, room_id, recording_id)
            await _release_file_lock(filepath)
            if result:
                return result
            # Split failed — fall through and upload as-is
            logger.warning(f"Split failed for {rec['filename']}, uploading original")
        return (filepath, recording_id)

    # Small file — find consecutive group in pending unsynced segments
    pending = await _get_pending_unsynced(room_id)
    group = _consecutive_group_for(pending, recording_id)

    # Collect group members that exist on disk
    valid: list[tuple] = []  # (row, filepath, size, duration)
    for seg in group:
        p = os.path.join(RECORDINGS_DIR, seg["filename"])
        if os.path.exists(p):
            sz = seg["size_bytes"] or os.path.getsize(p)
            dur = seg.get("_dur", 0)
            valid.append((seg, p, sz, dur))

    if not valid:
        return (filepath, recording_id)

    total_size = sum(sz for _, _, sz, _ in valid)
    total_dur = sum(dur for _, _, _, dur in valid)
    still_recording = await _is_room_still_recording(room_id)

    # Check if we've reached duration target — merge immediately
    if total_dur >= MERGE_TARGET_DUR:
        pass  # proceed to merge below
    # Not enough data and room still active — defer, but only up to STALE_WAIT_SECS
    elif total_dur < MERGE_TARGET_DUR and still_recording:
        # Check how long the oldest segment in the group has been waiting
        oldest_start = min(
            (seg["start_time"] for seg, _, _, _ in valid if seg["start_time"]),
            default=None,
        )
        wait_secs = 0
        if oldest_start:
            try:
                dt = datetime.fromisoformat(oldest_start.replace(" ", "T"))
                # DB stores local time without tzinfo — compare with local now
                if dt.tzinfo is None:
                    from datetime import datetime as _dt
                    wait_secs = int((_dt.now() - dt).total_seconds())
                else:
                    wait_secs = int(time.time() - dt.timestamp())
            except Exception:
                pass
        if wait_secs < STALE_WAIT_SECS:
            logger.info(
                f"Room {room_id}: small group {len(valid)} segs "
                f"~{total_dur:.0f}s < {MERGE_TARGET_DUR}s, "
                f"waiting for more segments (waited {wait_secs}s / {STALE_WAIT_SECS}s)"
            )
            return None
        logger.info(
            f"Room {room_id}: small group waited {wait_secs}s >= {STALE_WAIT_SECS}s, "
            "force-merging despite active recording"
        )

    # Only one file — upload as-is (can't merge alone)
    if len(valid) == 1:
        return (filepath, recording_id)

    # Select segments up to MERGE_TARGET_DUR, but never let the total exceed MERGE_MAX_DUR
    selected: list[tuple] = []
    selected_dur = 0
    for seg, p, sz, dur in valid:
        if selected_dur + dur > MERGE_MAX_DUR:
            break  # adding this file would push merged duration over 20 min
        if selected_dur >= MERGE_TARGET_DUR:
            break  # already at target duration
        selected.append((seg, p, sz, dur))
        selected_dur += dur

    if len(selected) <= 1:
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

    file_paths = [p for _, p, _, _ in selected]
    total_sel_size = sum(sz for _, _, sz, _ in selected)
    logger.info(
        f"Room {room_id}: merging {len(selected)} segments "
        f"(~{total_dur:.0f}s, {total_sel_size // 1024 // 1024}MB) → {merged_filename}"
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
    other_ids = [seg["id"] for seg, _, _, _ in selected[1:]]

    async with aio_connect() as db:
        await db.execute(
            "UPDATE recordings SET filename=?, size_bytes=? WHERE id=?",
            (merged_filename, merged_size, first_id),
        )
        if other_ids:
            placeholders = ",".join("?" * len(other_ids))
            await db.execute(
                f"UPDATE recordings SET local_deleted=1 WHERE id IN ({placeholders})",
                other_ids,
            )
        await db.commit()

    logger.info(
        f"Room {room_id}: merged → {merged_filename} "
        f"({merged_size // 1024 // 1024}MB, absorbed ids={other_ids})"
    )
    return (merged_path, first_id)
