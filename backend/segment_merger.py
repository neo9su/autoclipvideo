from gpu_execution import reject_local_media
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
from duration_policy import classify_duration, probe_duration

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
SPLIT_THRESHOLD  = 8 * 1024 * 1024   # files larger than this get split before upload (GPU service limit ~10MB)
SPLIT_CHUNK_SIZE = 6 * 1024 * 1024   # target chunk size when splitting large files (below GPU limit)

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
        duration = await probe_duration(os.path.join(RECORDINGS_DIR, d["filename"]))
        status = classify_duration(duration)
        if status != "accepted":
            async with aio_connect() as db:
                await db.execute(
                    "UPDATE recordings SET duration_seconds=?, duration_status=?, skip_reason=? WHERE id=?",
                    (duration if status == "too_short" else None, status, status, d["id"]),
                )
                await db.commit()
            continue
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
    Returns None if local media operations are disabled or split fails.
    """
    # Note: Local ffmpeg splits are allowed here; if unavailable, return None
    # to fall through to normal upload (remote will reject if too large)
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
            "SELECT group_id, segment_index, start_time, end_time FROM recordings WHERE id=?", (recording_id,)
        ) as cur:
            row = await cur.fetchone()
        group_id = row[0] if row else None
        base_index = row[1] if row else 0
        start_time = row[2] if row else ""
        end_time   = row[3] if row else ""

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
                   (room_id, group_id, filename, size_bytes, synced, transcribed,
                    local_deleted, segment_index, start_time, end_time,
                    duration_status)
                   VALUES (?, ?, ?, ?, 0, 0, 0, ?, ?, ?, 'accepted')""",
                (room_id, group_id, os.path.basename(cp), csz, base_index + i, start_time, end_time),
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
    """Select a validated source file; SRT is not required before upload.

    Transcription is the producer of the SRT sidecar, so checking for one here
    would deadlock every newly-finished recording.  Chunk splitting remains
    unchanged: the original row is the primary row for chunk 0 and additional
    chunks are registered as independent pending rows.
    """
    async with aio_connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, filename, size_bytes, local_deleted, synced FROM recordings WHERE id=?",
            (recording_id,),
        ) as cur:
            rec = await cur.fetchone()
    if not rec or rec["local_deleted"] or rec["synced"]:
        return None
    filepath = os.path.join(RECORDINGS_DIR, rec["filename"])
    if not os.path.isfile(filepath):
        reason = f"source media unavailable: {rec['filename']}"
        logger.warning("Recording %s cannot be uploaded: %s", recording_id, reason)
        async with aio_connect() as db:
            await db.execute(
                "UPDATE recordings SET transcribed=-1, transcribe_error=? "
                "WHERE id=? AND transcribed=0 AND synced=0",
                (reason, recording_id),
            )
            await db.commit()
        return None
    
    file_size = os.path.getsize(filepath)
    if file_size <= 0:
        reason = f"source media invalid: empty file: {rec['filename']}"
        logger.warning("Recording %s cannot be uploaded: %s", recording_id, reason)
        async with aio_connect() as db:
            await db.execute(
                "UPDATE recordings SET transcribed=-1, transcribe_error=?, skip_reason=? "
                "WHERE id=? AND transcribed=0 AND synced=0",
                (reason, reason, recording_id),
            )
            await db.commit()
        return None
    
    # Do not split a logical recording into database rows.  A database row is
    # a transcription/editing task, whereas upload framing is a transport
    # concern.  Splitting here used to create independent jobs with local
    # timestamps starting at zero and could silently discard all but chunk 0.
    # The GPU endpoint accepts streamed multipart bodies, so keep the complete
    # source intact and let the transport retry the request as a whole.
    if file_size > SPLIT_THRESHOLD:
        logger.info(
            "Keeping large recording %s as one logical task (%d MB)",
            rec["filename"], file_size // 1024 // 1024,
        )
    return filepath, recording_id


# Legacy local merge helpers are intentionally retained below for migration
# compatibility but are unreachable from the job workflow.
