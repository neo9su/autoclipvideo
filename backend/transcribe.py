from gpu_execution import reject_local_media
from duration_policy import MIN_RECORDING_DURATION_SECONDS, UNAVAILABLE_REASON, classify_duration, duration_reason
import asyncio
import calendar
import heapq
import logging
import os
import time
from pathlib import Path
from typing import Optional

import aiohttp
import aiosqlite
import httpx

from db import DB_PATH, aio_connect
from editor import edit_recording, edit_recording_multi
from analyzer import analyze_recording
from thumbnail import generate_thumbnail
from final_video import postprocess_final_video
from gpu_execution import reject_local_media
from srt_resolver import resolve_srt_path

logger = logging.getLogger(__name__)

GPU_SERVICE_URL = os.environ.get("GPU_SERVICE_URL", "http://10.190.0.203:8877")

MIN_RECORDING_HEIGHT = 720  # recordings below this height are skipped from clip jobs
MIN_RECORDING_DURATION = MIN_RECORDING_DURATION_SECONDS
MIN_FINAL_VIDEO_DURATION = 28.0  # director/creative final clips below this are not worth rescuing
TARGET_PUBLISH_DURATION = 30.5  # pad near-threshold clips above Douyin's 30s boundary


async def _get_video_duration(mp4_path: str) -> float:
    """Probe video duration using local ffprobe."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            mp4_path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        value = float(stdout.strip())
        return value if value > 0 else 0.0
    except Exception:
        return 0.0


async def _get_video_height(mp4_path: str) -> int:
    """Probe video height using local ffprobe."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=height",
            "-of", "default=noprint_wrappers=1:nokey=1",
            mp4_path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        return int(stdout.strip())
    except Exception:
        return 0


# In-memory clip job progress: {recording_id: {"phase": str, "step": int, "total": int, "pct": int, "msg": str}}
_clip_progress: dict = {}

# Poll loop health state — exposed via /api/gpu/status
_poll_state: dict = {
    "last_poll_at": None,       # epoch float
    "last_submit_at": None,     # epoch float: last time a job was sent to GPU
    "last_complete_at": None,   # epoch float: last transcription finished
    "last_poll_finished_at": None,
    "poll_count": 0,
    "last_poll_error": None,
    "blocked_count": 0,         # items blocked by merger on last poll
    "active_job_id": None,      # gpu_job_id currently running on GPU
    "poll_started_at": None,
    "stale_recovery_count": 0,
    "last_recovery_at": None,
    "last_recovery_job_id": None,
    "diagnosis": {"counts": {}, "samples": [], "can_submit_count": 0, "blocked_reason": None},
}

# Event to wake the poll loop immediately (used by the flush endpoint)
_flush_event: asyncio.Event = asyncio.Event()
# Explicit retranscription requests can opt out of automatic clipping.  This
# keeps validation of a single recording isolated from director/creative work.
_retranscribe_without_clip: set[int] = set()
RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), "..", "recordings")
POLL_INTERVAL = 60  # seconds
STALE_TRANSCRIBE_SECONDS = int(os.environ.get("STALE_TRANSCRIBE_SECONDS", "3600"))

# Pipeline concurrency: GPU has headroom (RTX 4080S 16GB), LLM semaphore is separate (=3).
# Director and creative use independent semaphores to maximize throughput.
# Increased to 4 to reduce backlog (515 jobs pending, GPU idle ~70h).
_DIRECTOR_SEM = asyncio.Semaphore(4)
_CREATIVE_SEM = asyncio.Semaphore(4)

# ── Transcription timing tracker ─────────────────────────────────────────────
_job_submit_times: dict[str, float] = {}   # gpu_job_id → time.time() when submitted
_job_durations: list[float] = []           # recent completed job durations (last 20)
_session_done: int = 0                     # jobs completed since backend start


def classify_transcription_record(
    row,
    *,
    media_exists: bool,
    gpu_online: bool,
    merge_blocked: bool = False,
    gpu_error: str | None = None,
) -> str:
    """Return a stable read-only reason for a transcription queue record."""
    if row.get("transcribed") == 1 and row.get("synced") == 1 and row.get("gpu_job_id"):
        return "gpu_job_running"
    if row.get("transcribed") == 2:
        return "transcription_complete"
    if row.get("local_deleted"):
        return "media_deleted"
    if row.get("transcribed") == -1:
        error = (row.get("transcribe_error") or row.get("skip_reason") or "").lower()
        return "srt_missing" if "srt" in error else "media_missing"
    if row.get("duration_status") != "accepted":
        return "duration_invalid"
    if not row.get("end_time") or row.get("end_time") == row.get("start_time"):
        return "end_time_invalid"
    if not media_exists:
        return "media_missing"
    if merge_blocked:
        return "merge_blocked"
    if not gpu_online or gpu_error:
        return "gpu_offline_or_error"
    return "ready_to_submit"

QUEUE_DIAGNOSIS_SAMPLE_LIMIT = 10


def _queue_sample(row, reason: str, *, status: str = "pending") -> dict:
    """Return a redacted, stable operator-facing queue sample."""
    return {
        "recording_id": row["id"],
        "filename": os.path.basename(row["filename"] or ""),
        "reason": reason,
        "status": status,
        "duration_status": row["duration_status"],
        "end_time_present": bool(row["end_time"]),
        "synced": row["synced"],
        "transcribed": row["transcribed"],
        "gpu_job_id": row["gpu_job_id"],
    }


async def transcription_queue_diagnosis(*, gpu_online: bool, gpu_error: str | None = None) -> dict:
    """Classify every unsynced transcription row without changing the database.

    This is intentionally a read-only audit helper.  Terminal source failures are
    recorded by the poller, while this endpoint only reports their current state.
    """
    counts: dict[str, int] = {}
    samples: list[dict] = []
    can_submit = 0
    async with aio_connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT id, filename, start_time, end_time, synced, transcribed,
                      local_deleted, duration_status, gpu_job_id, transcribe_error,
                      skip_reason
               FROM recordings
               WHERE (synced=0 AND transcribed IN (0, -1, 2))
                  OR (transcribed=1 AND gpu_job_id IS NOT NULL)
               ORDER BY id ASC"""
        ) as cur:
            rows = await cur.fetchall()

    merge_blocked_ids = {
        sample.get("recording_id")
        for sample in ((_poll_state.get("diagnosis") or {}).get("merge_samples") or [])
        if sample.get("recording_id") is not None
    }
    for row in rows:
        media_exists = os.path.isfile(os.path.join(RECORDINGS_DIR, row["filename"] or ""))
        reason = classify_transcription_record(
            row,
            media_exists=media_exists,
            gpu_online=gpu_online,
            merge_blocked=row["id"] in merge_blocked_ids,
            gpu_error=gpu_error,
        )
        if reason == "duration_invalid":
            reason = "duration_not_accepted"
        elif reason == "gpu_offline_or_error":
            reason = "gpu_error" if gpu_error else "gpu_offline"
        # A cached merge result is authoritative for the last poll cycle. Do
        # not report the same row as ready merely because the media still
        # exists while the merger is waiting for another chunk.
        if reason == "ready_to_submit" and row["id"] in merge_blocked_ids:
            reason = "merge_blocked"
        if reason == "ready_to_submit":
            can_submit += 1
        if reason == "gpu_job_running":
            sample_status = "running"
        else:
            sample_status = "pending"
        counts[reason] = counts.get(reason, 0) + 1
        if len(samples) < QUEUE_DIAGNOSIS_SAMPLE_LIMIT:
            samples.append(_queue_sample(row, reason, status=sample_status))

    poll_diagnosis = _poll_state.get("diagnosis") or {}
    merge_samples = poll_diagnosis.get("merge_samples", [])
    if merge_samples:
        counts["merge_blocked"] = poll_diagnosis.get("merge_blocked", len(merge_samples))
        samples.extend(merge_samples[:QUEUE_DIAGNOSIS_SAMPLE_LIMIT])
    blocked_reason = None
    if can_submit == 0:
        priority = ("gpu_error", "gpu_offline", "merge_blocked", "media_missing",
                    "srt_missing", "duration_invalid", "end_time_invalid")
        blocked_reason = next((item for item in priority if counts.get(item)), "queue_empty")
    return {
        "counts": counts,
        "samples": samples[:QUEUE_DIAGNOSIS_SAMPLE_LIMIT],
        "can_submit_count": can_submit,
        "blocked_reason": blocked_reason,
        "last_submit_at": _poll_state["last_submit_at"],
        "last_complete_at": _poll_state["last_complete_at"],
    }


async def mark_missing_source_media(recording_id: int, filename: str | None) -> None:
    """Persist a terminal, actionable error for a finished missing source."""
    basename = os.path.basename(filename or "") or "<unnamed>"
    reason = f"source media unavailable: {basename}"
    async with aio_connect() as db:
        await db.execute(
            """UPDATE recordings SET transcribed=-1, transcribe_error=?, skip_reason=?
               WHERE id=? AND transcribed=0 AND synced=0""",
            (reason, reason, recording_id),
        )
        await db.commit()
    logger.warning("Recording %s marked unavailable: %s", recording_id, reason)


def transcribe_timing() -> dict:
    recent = _job_durations[-10:] if _job_durations else []
    avg = sum(recent) / len(recent) if recent else 0.0
    return {
        "submit_times": dict(_job_submit_times),
        "avg_duration_s": avg,
        "session_done": _session_done,
    }

# ── Clip Job Priority Queue ───────────────────────────────────────────────────
# Jobs are dispatched up to MAX_CONCURRENT_CLIPS at a time, ordered by priority.
# Lower priority number = runs first. Default priority = 50.

MAX_CONCURRENT_CLIPS = int(os.environ.get("MAX_CONCURRENT_CLIPS", "1"))

_pending_heap: list = []          # heapq of [priority, seq, recording_id]
_pending_meta: dict = {}          # recording_id -> job metadata dict
_running_ids: set = set()         # recording_ids currently executing
_paused_ids: set = set()          # recording_ids paused (stay in heap, skip dispatch)
_job_seq: int = 0                 # monotonic tie-breaker for same-priority jobs
_dispatch_lock: Optional[asyncio.Lock] = None
_memory_pressure: bool = False    # set True to pause new clip dispatches when RAM > threshold


def set_memory_pressure(v: bool) -> None:
    global _memory_pressure
    _memory_pressure = v


def _dispatch_lk() -> asyncio.Lock:
    global _dispatch_lock
    if _dispatch_lock is None:
        _dispatch_lock = asyncio.Lock()
    return _dispatch_lock


async def _try_dispatch():
    """Start queued jobs if slots are available. Called after enqueue and after job completion."""
    to_start = []
    async with _dispatch_lk():
        skipped = []
        while _pending_heap and len(_running_ids) < MAX_CONCURRENT_CLIPS and not _memory_pressure:
            entry = heapq.heappop(_pending_heap)
            recording_id = entry[2]
            if recording_id in _paused_ids:
                skipped.append(entry)
                continue
            meta = _pending_meta.pop(recording_id, None)
            if meta is None:
                continue  # was cancelled/removed
            _running_ids.add(recording_id)
            to_start.append((recording_id, meta))
        for entry in skipped:
            heapq.heappush(_pending_heap, entry)

    for recording_id, meta in to_start:
        asyncio.create_task(_run_job_from_queue(recording_id, meta))


async def _run_job_from_queue(recording_id: int, meta: dict):
    """Execute a dequeued job, then trigger next dispatch."""
    try:
        await _do_edit(
            recording_id,
            meta["mp4_path"],
            meta["srt_path"],
            meta["clip_duration"],
            meta["clip_count"],
            meta["broadcast_fn"],
            feedback=meta.get("feedback"),
        )
    finally:
        async with _dispatch_lk():
            _running_ids.discard(recording_id)
        await _try_dispatch()


def get_clip_queue() -> dict:
    """Return current queue state for the API."""
    running = []
    for rid in _running_ids:
        p = _clip_progress.get(rid, {})
        running.append({
            "recording_id": rid,
            "status": "running",
            "priority": None,
            "phase": p.get("phase"),
            "pct": p.get("pct", 0),
            "msg": p.get("msg", ""),
            "eta_seconds": p.get("eta_seconds"),
        })

    # Build a sorted snapshot of the pending heap (doesn't modify the heap)
    queued = []
    paused = []
    for entry in sorted(_pending_heap):
        priority, seq, recording_id = entry
        meta = _pending_meta.get(recording_id)
        if meta:
            p = _clip_progress.get(recording_id, {})
            item = {
                "recording_id": recording_id,
                "status": "paused" if recording_id in _paused_ids else "queued",
                "priority": meta["priority"],
                "phase": p.get("phase", "queued"),
                "pct": 0,
                "msg": p.get("msg", "排队中"),
                "eta_seconds": None,
                "room_name": meta.get("room_name", ""),
                "record_date": meta.get("record_date", ""),
            }
            if recording_id in _paused_ids:
                paused.append(item)
            else:
                queued.append(item)

    return {"running": running, "queued": queued, "paused": paused}


async def update_job_priority(recording_id: int, priority: int) -> bool:
    """Update priority for a queued (not yet running) job. Returns True if updated."""
    async with _dispatch_lk():
        if recording_id not in _pending_meta:
            return False
        meta = _pending_meta[recording_id]
        old_seq = meta["seq"]
        meta["priority"] = priority
        # Remove old heap entry and re-insert with new priority
        _pending_heap[:] = [e for e in _pending_heap if e[2] != recording_id]
        heapq.heappush(_pending_heap, [priority, old_seq, recording_id])
    return True


async def cancel_clip_job(recording_id: int) -> bool:
    """Remove a queued/paused job from the dispatch queue. Cannot cancel running jobs."""
    async with _dispatch_lk():
        if recording_id not in _pending_meta:
            return False
        _pending_meta.pop(recording_id, None)
        _pending_heap[:] = [e for e in _pending_heap if e[2] != recording_id]
        _paused_ids.discard(recording_id)
    _clip_progress.pop(recording_id, None)
    return True


async def pause_clip_job(recording_id: int) -> bool:
    """Pause a queued job so it won't be dispatched until resumed. Returns True if found."""
    async with _dispatch_lk():
        if recording_id not in _pending_meta or recording_id in _running_ids:
            return False
        _paused_ids.add(recording_id)
    return True


async def resume_clip_job(recording_id: int) -> bool:
    """Resume a paused job. Returns True if it was paused."""
    async with _dispatch_lk():
        if recording_id not in _paused_ids:
            return False
        _paused_ids.discard(recording_id)
    await _try_dispatch()
    return True


async def _validate_mp4(filepath: str) -> tuple[bool, str]:
    """Validate media on the remote GPU; never invoke local ffprobe."""
    # Local validation is acceptable for sync recovery on the main backend
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        filepath,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=3.0)
        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()[-200:]
            return False, f"invalid mp4: {err}"
        duration_str = stdout.decode().strip()
        try:
            if float(duration_str) <= 0:
                return False, "invalid mp4: duration is 0"
        except ValueError:
            return False, f"invalid mp4: bad duration '{duration_str}'"
        return True, ""
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return False, "invalid mp4: ffprobe timeout (>3s)"
    except Exception as e:
        return False, f"invalid mp4: {e}"


async def flush_poll() -> None:
    """Wake the poll loop immediately (called by the flush API endpoint)."""
    _flush_event.set()


async def poll_transcriptions(broadcast_fn=None):
    """
    Background loop: poll GPU service for completed transcriptions and retry failed uploads.

    Uses gpu_state.wait_until_online() so the loop wakes up immediately when the GPU
    service comes back online instead of waiting out a fixed sleep interval.
    """
    from gpu_state import is_online, wait_until_online

    # Startup recovery: re-trigger editor for recordings whose transcription completed
    # but whose clip task was lost (e.g. backend restarted mid-flight).
    # Also recovers "stuck" jobs where clipped=1 (clipping in progress) but
    # clip_filename is NULL — meaning _do_edit crashed before writing the result.
    # Throttled: at most 5 per batch, with a 2s pause between batches, to avoid
    # flooding the queue with hundreds of tasks at startup and pegging local CPU.
    _STARTUP_RECOVERY_BATCH = 5
    try:
        async with aio_connect() as db:
            db.row_factory = aiosqlite.Row
            # Case 1: normal pending (clipped=0)
            async with db.execute(
                "SELECT id, filename, clip_count FROM recordings "
                "WHERE transcribed=2 AND clipped=0 AND local_deleted=0 "
                "AND duration_status='accepted'"
            ) as cur:
                pending = await cur.fetchall()
            # Case 2: stuck mid-clipping (clipped=1, no clip_filename)
            async with db.execute(
                "SELECT id, filename, clip_count FROM recordings "
                "WHERE transcribed=2 AND clipped=1 AND clip_filename IS NULL "
                "AND local_deleted=0 AND clip_error IS NULL AND duration_status='accepted'"
            ) as cur:
                stuck = await cur.fetchall()
        # Reset stuck jobs back to pending
        stuck_ids = []
        if stuck:
            async with aio_connect() as db:
                placeholders = ",".join(["?"] * len(stuck))
                await db.execute(
                    f"UPDATE recordings SET clipped = 0 WHERE id IN ({placeholders})",
                    [r["id"] for r in stuck],
                )
                await db.commit()
            stuck_ids = [r["id"] for r in stuck]
            logger.info(f"Startup recovery: reset {len(stuck_ids)} stuck clip job(s) from clipped=1 to clipped=0")
        # Merge pending and stuck for recovery dispatch
        orphaned = list(pending)
        orphaned.extend(stuck)
        recoverable = []
        for rec in orphaned:
            mp4_path = os.path.join(RECORDINGS_DIR, rec["filename"])
            srt_path = resolve_srt_path(mp4_path)
            if os.path.isfile(mp4_path) and srt_path:
                recoverable.append((rec, mp4_path, srt_path))
            elif os.path.isfile(mp4_path) and not srt_path:
                # A completed row can lose its downloaded sidecar when the
                # backend is restarted between GPU completion and SRT write.
                # Re-queue the source instead of marking it as missing media;
                # the GPU endpoint's content idempotency key prevents a
                # duplicate remote job when the original is still retained.
                logger.warning(
                    "Startup recovery: recording %s has MP4 but no SRT; re-queuing transcription",
                    rec["id"],
                )
                async with aio_connect() as db:
                    await db.execute(
                        """UPDATE recordings
                           SET synced=0, transcribed=0, gpu_job_id=NULL,
                               transcribe_error=NULL, skip_reason=NULL,
                               clipped=0, clip_error=NULL
                           WHERE id=? AND transcribed=2""",
                        (rec["id"],),
                    )
                    await db.commit()
            else:
                await _mark_unprocessable_source(
                    rec["id"],
                    mp4_exists=os.path.isfile(mp4_path),
                    srt_exists=bool(srt_path),
                    context="startup recovery",
                )
        if recoverable:
            logger.info(f"Startup recovery: {len(recoverable)} recordings to re-trigger (batch size {_STARTUP_RECOVERY_BATCH})")
        for i in range(0, len(recoverable), _STARTUP_RECOVERY_BATCH):
            batch = recoverable[i:i + _STARTUP_RECOVERY_BATCH]
            for rec, mp4_path, srt_path in batch:
                logger.info(f"Startup recovery: re-triggering editor for recording {rec['id']} ({rec['filename']})")
                asyncio.create_task(
                    _run_editor(rec["id"], mp4_path, srt_path,
                                clip_count=rec["clip_count"] or 1,
                                broadcast_fn=broadcast_fn)
                )
            if i + _STARTUP_RECOVERY_BATCH < len(recoverable):
                await asyncio.sleep(2)  # pause between batches to avoid startup CPU spike
    except Exception as e:
        logger.error(f"Startup recovery error: {e}")

    while True:
        try:
            _poll_state["poll_started_at"] = time.time()
            _poll_state["last_poll_at"] = _poll_state["poll_started_at"]
            async with aio_connect() as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM recordings WHERE transcribed = 1 AND gpu_job_id IS NOT NULL "
                    "AND duration_status = 'accepted'"
                ) as cur:
                    pending = await cur.fetchall()
                async with db.execute(
                    """SELECT * FROM recordings
                       WHERE synced = 0 AND transcribed = 0 AND local_deleted = 0
                         AND end_time IS NOT NULL AND end_time != start_time
                         AND duration_status = 'accepted'"""
                    ) as cur:
                    unsynced = await cur.fetchall()

            diagnosis = await transcription_queue_diagnosis(
                gpu_online=is_online(),
                gpu_error=_poll_state.get("last_poll_error"),
            )
            _poll_state["diagnosis"] = diagnosis

            available_unsynced = []
            for rec in unsynced:
                filepath = os.path.join(RECORDINGS_DIR, rec["filename"])
                if os.path.isfile(filepath):
                    available_unsynced.append(rec)
                else:
                    await mark_missing_source_media(rec["id"], rec["filename"])
            unsynced = available_unsynced

            has_work = bool(pending or unsynced)

            if has_work and not is_online():
                # GPU is offline — wait for the watcher to signal it is back,
                # but cap wait at POLL_INTERVAL so we re-check DB state periodically.
                logger.debug("GPU offline, waiting for recovery before processing jobs")
                try:
                    await asyncio.wait_for(wait_until_online(), timeout=POLL_INTERVAL)
                except asyncio.TimeoutError:
                    pass
                # Re-enter loop regardless (watcher may have flipped state)
                continue

            if pending and is_online():
                for rec in pending:
                    await _check_job(rec, broadcast_fn)

            if is_online():
                from segment_merger import maybe_merge_before_upload
                from sync import sync_file
                from comfyui_client import free_vram
                blocked = 0
                merge_samples = []
                vram_freed = False  # freed at most once per poll cycle
                for rec in unsynced:
                    if not is_online():
                        logger.debug("GPU went offline mid-upload loop, stopping")
                        break
                    filepath = os.path.join(RECORDINGS_DIR, rec["filename"])
                    if not os.path.exists(filepath):
                        await _mark_unprocessable_source(
                            rec["id"], mp4_exists=False, srt_exists=None,
                            context="transcription upload",
                        )
                        continue
                    if not os.access(filepath, os.R_OK):
                        await _mark_unprocessable_source(
                            rec["id"], mp4_exists=True, srt_exists=None,
                            context="transcription upload",
                        )
                        continue
                    # SRT is produced by the GPU job and fetched after completion.
                    # The merger only selects/splits the MP4 source.
                    result = await maybe_merge_before_upload(rec["room_id"], rec["id"])
                    if result is None:
                        # The merger returns None for terminal source errors or
                        # when a split/merge operation cannot produce a source.
                        # Missing SRT is intentionally not checked here: the GPU
                        # transcription result creates it after upload.
                        if not os.path.isfile(filepath):
                            await _mark_unprocessable_source(
                                rec["id"], mp4_exists=False, srt_exists=None,
                                context="transcription upload",
                            )
                        async with aio_connect() as db:
                            async with db.execute(
                                "SELECT transcribed, synced FROM recordings WHERE id=?",
                                (rec["id"],),
                            ) as cur:
                                current = await cur.fetchone()
                        if current and current[0] == 0 and current[1] == 0:
                            blocked += 1
                            merge_samples.append({
                                "recording_id": rec["id"],
                                "filename": os.path.basename(rec["filename"] or ""),
                                "reason": "merge_blocked",
                                "status": "pending",
                            })
                        continue
                    upload_path, primary_id = result
                    # The queue snapshot is intentionally taken before the
                    # upload loop.  Re-check the row so a concurrent poll
                    # cycle (or a manual retry) cannot submit a row that was
                    # already claimed and associated with a GPU job.
                    async with aio_connect() as db:
                        async with db.execute(
                            "SELECT synced, transcribed, gpu_job_id FROM recordings WHERE id=?",
                            (primary_id,),
                        ) as cur:
                            current = await cur.fetchone()
                    if not current or current[0] or current[2] or current[1] != 0:
                        logger.info("Skipping recording %s: upload already claimed", primary_id)
                        continue
                    valid, err_msg = await _validate_mp4(upload_path)
                    if not valid:
                        logger.warning(f"Skipping corrupt file {os.path.basename(upload_path)}: {err_msg}")
                        async with aio_connect() as db:
                            await db.execute(
                                "UPDATE recordings SET transcribed=-1, transcribe_error=? WHERE id=?",
                                (err_msg, primary_id),
                            )
                            await db.commit()
                        continue
                    if not vram_freed:
                        await free_vram()
                        vram_freed = True
                    logger.info(f"Uploading {os.path.basename(upload_path)} to GPU service")
                    job_id = await sync_file(upload_path, rec["room_id"])
                    if job_id:
                        _job_submit_times[job_id] = time.time()
                        _poll_state["last_submit_at"] = time.time()
                        _poll_state["active_job_id"] = job_id
                        async with aio_connect() as db:
                            cursor = await db.execute(
                                "UPDATE recordings SET synced = 1, transcribed = 1, gpu_job_id = ?, upload_bytes = ? "
                                "WHERE id = ? AND synced = 0 AND transcribed = 0",
                                (job_id, os.path.getsize(upload_path), primary_id),
                            )
                            await db.commit()
                        if cursor.rowcount != 1:
                            logger.info("Recording %s was claimed before job %s could be persisted", primary_id, job_id)
                _poll_state["blocked_count"] = blocked
                _poll_state["diagnosis"]["merge_blocked"] = blocked
                _poll_state["diagnosis"]["merge_samples"] = merge_samples[:QUEUE_DIAGNOSIS_SAMPLE_LIMIT]
                if blocked and _poll_state["diagnosis"].get("can_submit_count", 0) == 0:
                    _poll_state["diagnosis"]["blocked_reason"] = "merge_blocked"
            _poll_state["poll_count"] += 1
            _poll_state["last_poll_error"] = None

        except asyncio.CancelledError:
            break
        except Exception as e:
            _poll_state["last_poll_error"] = type(e).__name__
            logger.exception(f"Transcription poll error: {e}")
        finally:
            # ``last_poll_at`` is the start heartbeat. This completion
            # heartbeat distinguishes a slow cycle from a dead poll loop.
            _poll_state["last_poll_finished_at"] = time.time()

        # Sleep until next interval, but wake immediately if flush_poll() is called
        try:
            await asyncio.wait_for(_flush_event.wait(), timeout=POLL_INTERVAL)
            _flush_event.clear()
        except asyncio.TimeoutError:
            pass


async def _mark_unprocessable_source(
    recording_id: int,
    *,
    mp4_exists: bool,
    srt_exists: bool | None,
    context: str,
) -> None:
    """Terminally classify a source that cannot enter the media pipeline.

    This is deliberately limited to rows still waiting for upload/editing. It
    never changes completed recordings and makes the reason visible to both the
    queue API and group matching instead of allowing a silent retry loop.
    """
    reason = _source_unavailable_reason(mp4_exists, srt_exists)
    logger.warning("%s: recording %s marked unprocessable (%s)", context, recording_id, reason)
    async with aio_connect() as db:
        await db.execute(
            """UPDATE recordings
               SET transcribed = CASE WHEN transcribed = 0 THEN -1 ELSE transcribed END,
                   clipped = CASE WHEN transcribed = 2 AND clipped IN (0, 1) THEN -1 ELSE clipped END,
                   synced = 0, gpu_job_id = NULL,
                   transcribe_error = ?, clip_error = CASE
                       WHEN transcribed = 2 AND clipped IN (0, 1) THEN ? ELSE clip_error END,
                   skip_reason = ?
               WHERE id = ? AND synced = 0 AND transcribed IN (0, 2)""",
            (reason, reason, reason, recording_id),
        )
        await db.commit()


def _source_unavailable_reason(mp4_exists: bool, srt_exists: bool | None) -> str:
    """Return a stable operator-facing reason for a failed source preflight."""
    if not mp4_exists:
        return "source media unavailable: recording file is missing"
    if srt_exists is False:
        return "source media/SRT unavailable: non-empty SRT sidecar is missing"
    return "source media unavailable: recording file is not readable"


async def _check_job(rec, broadcast_fn):
    job_id = rec["gpu_job_id"]
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{GPU_SERVICE_URL}/jobs/{job_id}",
                                   timeout=aiohttp.ClientTimeout(total=10)) as resp:
                _status_code = resp.status
                _json = await resp.json() if _status_code in (200, 404) else None
    except Exception as e:
        logger.warning(f"Cannot reach GPU service for job {job_id}: {e}")
        return

    if _status_code == 404:
        # GPU service restarted and lost this job — re-queue for upload
        logger.warning(f"Job {job_id} not found on GPU service (restarted?), re-queuing")
        from sync import invalidate_upload
        await invalidate_upload(
            os.path.join(RECORDINGS_DIR, rec["filename"]), rec["room_id"]
        )
        async with aio_connect() as db:
            await db.execute(
                "UPDATE recordings SET transcribed=0, synced=0, gpu_job_id=NULL WHERE id=?",
                (rec["id"],),
            )
            await db.commit()
        from sync import forget_upload_job
        forget_upload_job(job_id)
        return

    if _status_code != 200:
        return

    job = _json
    if job["status"] == "processing" and _is_stale_job(job):
        if await _recover_stale_job(rec):
            return
    if job["status"] == "done":
        global _session_done
        if job_id in _job_submit_times:
            dur = time.time() - _job_submit_times.pop(job_id)
            _job_durations.append(dur)
            if len(_job_durations) > 20:
                _job_durations.pop(0)
        _session_done += 1
        _poll_state["last_complete_at"] = time.time()
        _poll_state["active_job_id"] = None
        await _fetch_srt(rec["id"], job_id, rec["filename"], clip_count=rec["clip_count"] if "clip_count" in rec else 1, broadcast_fn=broadcast_fn)
        if broadcast_fn:
            try:
                await broadcast_fn({"type": "transcribed", "recording_id": rec["id"]})
            except Exception:
                pass
        # Method A: wake poll loop immediately so next job is submitted without waiting
        asyncio.create_task(flush_poll())
    elif job["status"] == "error":
        err_msg = (job.get("error") or "GPU 转录失败（未知错误）")[:300]
        logger.error(f"GPU transcription error for {rec['filename']}: {err_msg}")
        _job_submit_times.pop(job_id, None)  # prevent unbounded growth on errors
        if _poll_state["active_job_id"] == job_id:
            _poll_state["active_job_id"] = None
        async with aio_connect() as db:
            await db.execute(
                "UPDATE recordings SET transcribed = -1, transcribe_error = ? WHERE id = ?",
                (err_msg, rec["id"]),
            )
            await db.commit()


def _is_stale_job(job: dict, now: float | None = None) -> bool:
    now = now or time.time()
    stamp = job.get("heartbeat_at") or job.get("created_at")
    if stamp:
        try:
            return now - calendar.timegm(time.strptime(stamp[:19], "%Y-%m-%d %H:%M:%S")) >= STALE_TRANSCRIBE_SECONDS
        except (TypeError, ValueError, OverflowError):
            pass
    submitted = _job_submit_times.get(job.get("job_id"))
    return bool(submitted and now - submitted >= STALE_TRANSCRIBE_SECONDS)


async def _recover_stale_job(rec) -> bool:
    job_id = rec["gpu_job_id"]
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{GPU_SERVICE_URL}/jobs/{job_id}/recover", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                body = await resp.json() if resp.status in (200, 404) else {}
                if resp.status == 409 or (resp.status == 200 and not body.get("recovered")):
                    return False
                if resp.status not in (200, 404):
                    return False
    except Exception as exc:
        logger.warning("Cannot recover stale GPU job %s: %s", job_id, type(exc).__name__)
        return False
    _job_submit_times.pop(job_id, None)
    if _poll_state["active_job_id"] == job_id:
        _poll_state["active_job_id"] = None
    _poll_state["stale_recovery_count"] += 1
    _poll_state["last_recovery_at"] = time.time()
    _poll_state["last_recovery_job_id"] = job_id
    async with aio_connect() as db:
        await db.execute("UPDATE recordings SET transcribed=0, synced=0, gpu_job_id=NULL, transcribe_error=NULL WHERE id=? AND transcribed=1 AND gpu_job_id=?", (rec["id"], job_id))
        await db.commit()
    logger.warning("Recovered stale transcription job %s for recording %s", job_id, rec["id"])
    return True


async def _fetch_srt(recording_id: int, job_id: str, filename: str, clip_count: int = 1, broadcast_fn=None):
    srt_filename = os.path.splitext(filename)[0] + ".srt"
    local_srt = os.path.join(RECORDINGS_DIR, srt_filename)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{GPU_SERVICE_URL}/jobs/{job_id}/srt",
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                _srt_status = resp.status
                content = await resp.read() if _srt_status == 200 else b""
                expected_len = resp.headers.get("content-length")
        if _srt_status == 200:
            # Verify completeness against Content-Length header if present
            if expected_len and expected_len.isdigit() and len(content) != int(expected_len):
                logger.error(
                    f"SRT download truncated for {job_id}: "
                    f"got {len(content)} B, expected {expected_len} B — skipping"
                )
                reason = "SRT download incomplete"
                async with aio_connect() as db:
                    await db.execute(
                        "UPDATE recordings SET transcribed=-1, transcribe_error=?, skip_reason=? WHERE id=?",
                        (reason, reason, recording_id),
                    )
                    await db.commit()
                return
            if not content.strip():
                # Whisper produced 0 speech segments — no text in the video.
                # Treat as terminal failure so the recording doesn't retry forever.
                logger.warning(f"SRT empty for {job_id} — Whisper detected no speech, marking transcribe_error")
                async with aio_connect() as db:
                    await db.execute(
                        "UPDATE recordings SET transcribed = -1, transcribe_error = ? WHERE id = ?",
                        ("Whisper detected no speech segments (silent/music-only audio)", recording_id),
                    )
                    await db.commit()
                return
            with open(local_srt, "wb") as f:
                f.write(content)
            logger.info(f"SRT fetched: {srt_filename}")
            async with aio_connect() as db:
                await db.execute(
                    "UPDATE recordings SET transcribed = 2 WHERE id = ?", (recording_id,)
                )
                await db.commit()
            # Validation/retranscription requests may explicitly defer clipping.
            if recording_id not in _retranscribe_without_clip:
                mp4_path = os.path.join(RECORDINGS_DIR, filename)
                asyncio.create_task(_run_editor(recording_id, mp4_path, local_srt, clip_count=clip_count, broadcast_fn=broadcast_fn))
            else:
                _retranscribe_without_clip.discard(recording_id)
        else:
            logger.error(f"SRT download failed for {job_id}: {_srt_status}")
            reason = f"SRT unavailable after GPU transcription (HTTP {_srt_status})"
            async with aio_connect() as db:
                await db.execute(
                    "UPDATE recordings SET transcribed=-1, transcribe_error=?, skip_reason=? WHERE id=?",
                    (reason, reason, recording_id),
                )
                await db.commit()
    except Exception as e:
        logger.error(f"SRT fetch error for {job_id}: {e}")


async def _run_editor(recording_id: int, mp4_path: str, srt_path: str, clip_duration: Optional[float] = None, clip_count: int = 1, broadcast_fn=None, feedback: Optional[str] = None):
    """Enqueue a clip job into the priority queue and dispatch if a slot is free."""
    global _job_seq

    # ── Resolution guard ──────────────────────────────────────────────────────
    height = await _get_video_height(mp4_path)
    if 0 < height < MIN_RECORDING_HEIGHT:
        reason = f"分辨率过低（{height}p < {MIN_RECORDING_HEIGHT}p）"
        logger.warning(f"[skip] Recording {recording_id} ({os.path.basename(mp4_path)}): {reason}")
        async with aio_connect() as db:
            await db.execute(
                "UPDATE recordings SET clipped = -1, skip_reason = ? WHERE id = ?",
                (reason, recording_id),
            )
            await db.commit()
        return

    # ── Duration guard ────────────────────────────────────────────────────────
    duration = await _get_video_duration(mp4_path)
    duration_status = classify_duration(duration)
    if duration_status != "accepted":
        reason = duration_reason(duration)
        if duration_status == UNAVAILABLE_REASON:
            reason = f"{UNAVAILABLE_REASON}: {reason}"
        logger.warning(f"[skip] Recording {recording_id} ({os.path.basename(mp4_path)}): {reason}")
        async with aio_connect() as db:
            await db.execute(
                "UPDATE recordings SET clipped = -1, duration_seconds = ?, duration_status = ?, skip_reason = ? WHERE id = ?",
                (duration or None, duration_status, reason, recording_id),
            )
            await db.commit()
        return

    async with aio_connect() as db:
        await db.execute(
            "UPDATE recordings SET clipped = 1 WHERE id = ?", (recording_id,)
        )
        await db.commit()

    # Fetch room info for display in queue
    room_name, record_date = "unknown", ""
    try:
        async with aio_connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT r.start_time, rm.name as room_name "
                "FROM recordings r JOIN rooms rm ON r.room_id = rm.id WHERE r.id = ?",
                (recording_id,)
            ) as cur:
                info = await cur.fetchone()
        if info:
            room_name = info["room_name"] or "unknown"
            record_date = (info["start_time"] or "")[:10].replace("-", "")
    except Exception:
        pass

    # Enqueue with default priority=50
    async with _dispatch_lk():
        _job_seq += 1
        seq = _job_seq
        priority = 50
        heapq.heappush(_pending_heap, [priority, seq, recording_id])
        _pending_meta[recording_id] = {
            "priority": priority,
            "seq": seq,
            "mp4_path": mp4_path,
            "srt_path": srt_path,
            "clip_duration": clip_duration,
            "clip_count": clip_count,
            "broadcast_fn": broadcast_fn,
            "room_name": room_name,
            "record_date": record_date,
            "feedback": feedback,
        }

    _clip_progress[recording_id] = {
        "phase": "queued", "step": 0, "total": 1, "pct": 0, "msg": "排队中",
        "variant": 0, "eta_seconds": None, "started_at": time.time(),
    }
    if broadcast_fn:
        try:
            await broadcast_fn({"type": "clip_progress", "recording_id": recording_id, "pct": 0, "msg": "排队中", "eta_seconds": None})
        except Exception:
            pass

    await _try_dispatch()


async def _do_edit(recording_id: int, mp4_path: str, srt_path: str, clip_duration: Optional[float], clip_count: int, broadcast_fn, feedback: Optional[str] = None):
    """Actual editing work, called after acquiring the concurrency semaphore."""
    # ── Progress tracking ────────────────────────────────────────────────────
    _PHASE_LABELS = {
        "build":      "准备",
        "preprocess": "预处理片段",
        "merge":      "合并片段",
        "final":      "字幕+音乐",
        "thumbnail":  "生成封面",
    }
    # Weight allocation per phase (must sum to 100 across a single clip build)
    # preprocess: 0-50%, merge: 50-75%, final: 75-85%, thumbnail: 85-100%
    _clip_count_total = max(1, min(5, clip_count))

    _job_started_at = time.time()

    async def _on_progress(phase: str, step: int, total: int):
        # Compute percentage within a single clip's phases
        if phase == "preprocess":
            pct_in_clip = int(10 + (step / max(total, 1)) * 40)   # 10→50%
        elif phase == "merge":
            pct_in_clip = int(50 + (step / max(total, 1)) * 25)   # 50→75%
        elif phase == "final":
            pct_in_clip = 80
        elif phase == "thumbnail":
            pct_in_clip = 92
        elif phase == "build":
            pct_in_clip = 5
        else:
            pct_in_clip = 0

        current_variant = _clip_progress.get(recording_id, {}).get("variant", 0)
        if phase == "build":
            current_variant = step
        base = int(current_variant / _clip_count_total * 100)
        scale = 1.0 / _clip_count_total
        pct = min(99, int(base + pct_in_clip * scale))

        label = _PHASE_LABELS.get(phase, phase)
        if total > 1 and phase in ("preprocess", "merge"):
            msg = f"{label} {step}/{total}"
        else:
            msg = label

        # ETA: estimate remaining seconds from elapsed time and progress
        eta_seconds = None
        if pct >= 3:
            elapsed = time.time() - _job_started_at
            eta_seconds = int(elapsed * (100 - pct) / pct)

        _clip_progress[recording_id] = {
            "phase": phase,
            "step": step,
            "total": total,
            "pct": pct,
            "msg": msg,
            "variant": current_variant,
            "eta_seconds": eta_seconds,
            "started_at": _job_started_at,
        }
        if broadcast_fn:
            try:
                await broadcast_fn({
                    "type": "clip_progress",
                    "recording_id": recording_id,
                    "pct": pct,
                    "msg": msg,
                    "eta_seconds": eta_seconds,
                })
            except Exception:
                pass

    _clip_progress[recording_id] = {
        "phase": "start", "step": 0, "total": 1, "pct": 0, "msg": "分析中",
        "variant": 0, "eta_seconds": None, "started_at": _job_started_at,
    }

    try:
        # Fetch room name, room_id and recording date for organised output path
        room_name = "unknown"
        date_str = ""
        rec_room_id = None
        try:
            async with aio_connect() as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT r.start_time, r.room_id, rm.name as room_name "
                    "FROM recordings r JOIN rooms rm ON r.room_id = rm.id WHERE r.id = ?",
                    (recording_id,)
                ) as cur:
                    info = await cur.fetchone()
            if info:
                room_name = info["room_name"] or "unknown"
                date_str = (info["start_time"] or "")[:10].replace("-", "")
                rec_room_id = info["room_id"]
        except Exception as e:
            logger.warning(f"Could not fetch room info for recording {recording_id}: {e}")

        clip_count = max(1, min(5, clip_count))

        # Read clip_engine from settings (default: "legacy")
        clip_engine = "legacy"
        try:
            async with aio_connect() as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT value FROM settings WHERE key = 'clip_engine'"
                ) as cur:
                    row = await cur.fetchone()
            if row and row["value"] in ("legacy", "v2", "realistic", "conservative"):
                clip_engine = row["value"]
        except Exception as e:
            logger.warning(f"Could not read clip_engine setting: {e}")
        logger.info(f"clip_engine={clip_engine} for recording {recording_id}")

        if clip_count == 1:
            clip_path = await edit_recording(mp4_path, srt_path, room_name=room_name, record_date=date_str, clip_duration=clip_duration, on_progress=_on_progress, feedback=feedback, room_id=rec_room_id, clip_engine=clip_engine)
            clip_paths = [clip_path] if clip_path else []
        else:
            clip_paths = await edit_recording_multi(mp4_path, srt_path, count=clip_count, room_name=room_name, record_date=date_str, clip_duration=clip_duration, on_progress=_on_progress, feedback=feedback, room_id=rec_room_id, clip_engine=clip_engine)

        if clip_paths:
            c_dur = clip_duration or 30.0
            from editor import _clip_job_id_cache
            async with aio_connect() as db:
                for k, clip_path in enumerate(clip_paths):
                    clip_filename = os.path.relpath(clip_path, RECORDINGS_DIR)
                    offset = max(3.0, c_dur * (0.2 + 0.3 * k))
                    # Thumbnail generation is presentation-only.  The control
                    # plane deliberately rejects local media execution, so a
                    # policy error here must not discard a valid remote clip
                    # or make it ineligible for SRT/qianchuan matching.
                    try:
                        thumb = await generate_thumbnail(clip_path, offset=offset)
                    except Exception as exc:
                        logger.warning(
                            "Optional thumbnail skipped for recording %s: %s",
                            recording_id,
                            str(exc)[:200],
                        )
                        thumb = None
                    thumb_basename = os.path.relpath(thumb, RECORDINGS_DIR) if thumb else None
                    gpu_job_id = _clip_job_id_cache.pop(clip_path, None)

                    if k == 0:
                        await db.execute(
                            "UPDATE recordings SET clipped = 2, clip_filename = ?, thumbnail = ? WHERE id = ?",
                            (clip_filename, thumb_basename, recording_id),
                        )

                    await db.execute(
                        "INSERT INTO recording_clips (recording_id, variant_idx, clip_filename, thumbnail, gpu_clip_job_id) VALUES (?, ?, ?, ?, ?)",
                        (recording_id, k, clip_filename, thumb_basename, gpu_job_id),
                    )

                # Get room_id for analysis
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT room_id, filename FROM recordings WHERE id = ?", (recording_id,)
                ) as cur:
                    rec = await cur.fetchone()
                await db.commit()

            logger.info(f"Clips saved: {len(clip_paths)} variant(s) for recording {recording_id}")
            _clip_progress.pop(recording_id, None)
            if rec:
                asyncio.create_task(
                    analyze_recording(recording_id, rec["filename"], rec["room_id"])
                )
                asyncio.create_task(_maybe_auto_merge(recording_id))
        else:
            logger.warning(f"Editor produced no clips for recording {recording_id}")
            async with aio_connect() as db:
                await db.execute(
                    "UPDATE recordings SET clipped = -1, clip_error = ? WHERE id = ?",
                    ("no clips selected", recording_id),
                )
                await db.commit()
            _clip_progress.pop(recording_id, None)
    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        logger.error(f"Editor failed for recording {recording_id}: {e}\n{err_msg}")
        async with aio_connect() as db:
            await db.execute(
                "UPDATE recordings SET clipped = -1, clip_error = ? WHERE id = ?",
                (str(e)[:500], recording_id),
            )
            await db.commit()
        _clip_progress.pop(recording_id, None)


async def _maybe_auto_merge(recording_id: int):
    """After a clip finishes, auto-merge the group if all active recordings are clipped=2.

    clipped=-1 (skipped: low-res / too-short) recordings are excluded from the
    check so a group with some skipped files can still auto-merge.
    """
    try:
        async with aio_connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT group_id FROM recordings WHERE id = ?", (recording_id,)
            ) as cur:
                row = await cur.fetchone()
            if not row or not row["group_id"]:
                return
            group_id = row["group_id"]
            await _auto_merge_group(db, group_id)
    except Exception as e:
        logger.error(f"Auto-merge failed for group of recording {recording_id}: {e}")


async def _auto_merge_group(db, group_id: int) -> bool:
    """Check readiness and trigger classic+director+creative pipelines for a group. Returns True if any triggered."""
    from analyzer import merge_group as _merge_group

    # Count active (non-skipped) recordings; all must be clipped=2
    async with db.execute(
        "SELECT "
        "  COUNT(*) FILTER (WHERE clipped != -1) as active, "
        "  COUNT(*) FILTER (WHERE clipped  =  2) as done "
        "FROM recordings WHERE group_id = ?",
        (group_id,),
    ) as cur:
        counts = await cur.fetchone()
    if not counts or counts["active"] == 0 or counts["active"] != counts["done"]:
        return False

    # Check per-pipeline statuses (0=not started, 1=running, 2=done, -1=failed)
    async with db.execute(
        "SELECT classic_status, director_status, creative_status, realistic_status, conservative_status, qianchuan_status FROM clip_groups WHERE id = ?", (group_id,)
    ) as cur:
        grp = await cur.fetchone()
    if not grp:
        return False

    triggered = False
    if grp["classic_status"] == 0:
        logger.info(f"Auto-triggering classic merge for group {group_id}")
        asyncio.create_task(_merge_group(group_id))
        triggered = True
    if grp["director_status"] in (0, -1, -3):
        logger.info(f"Auto-triggering director pipeline for group {group_id}")
        asyncio.create_task(_run_director_pipeline(group_id))
        triggered = True
    if (grp["creative_status"] or 0) == 0:
        logger.info(f"Auto-triggering creative pipeline for group {group_id}")
        asyncio.create_task(_run_creative_pipeline(group_id))
        triggered = True
    if (grp["qianchuan_status"] or 0) in (0, -1, -3, -4):
        logger.info(f"Auto-triggering qianchuan pipeline for group {group_id}")
        from api_v2 import _run_qianchuan_pipeline
        asyncio.create_task(_run_qianchuan_pipeline(group_id))
        triggered = True
    for variant in ("realistic", "conservative"):
        if (grp[f"{variant}_status"] or 0) in (0, -1, -3):
            asyncio.create_task(_run_variant_pipeline(group_id, variant))
            triggered = True
    return triggered


async def _run_variant_pipeline(group_id: int, variant: str, status_claimed: bool = False) -> None:
    """Generate a publishable variant through the recording clip engine."""
    if variant not in ("realistic", "conservative"):
        raise ValueError("unsupported publish variant")
    status_field = f"{variant}_status"
    error_field = f"{variant}_error"
    output_field = f"{variant}_final_video"
    try:
        async with aio_connect() as db:
            if status_claimed:
                await db.execute(
                    f"UPDATE clip_groups SET {error_field}=NULL WHERE id=? AND {status_field}=1",
                    (group_id,),
                )
            else:
                await db.execute(f"UPDATE clip_groups SET {status_field}=1, {error_field}=NULL WHERE id=? AND {status_field} IN (0, 1, -1, -3)", (group_id,))
            await db.commit()
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT r.id, r.filename, r.room_id, r.start_time FROM recordings r "
                "WHERE r.group_id=? AND r.duration_status = 'accepted' "
                "AND (r.clipped=2 OR r.clip_filename IS NOT NULL) "
                "ORDER BY r.start_time ASC",
                (group_id,),
            ) as cur:
                recordings = await cur.fetchall()
            async with db.execute("SELECT wig_model, wig_color FROM clip_groups WHERE id=?", (group_id,)) as cur:
                group = await cur.fetchone()
        if not recordings:
            raise RuntimeError("no source recordings in group")
        from editor import edit_recording
        generated = []
        for recording in recordings:
            source_path = os.path.join(RECORDINGS_DIR, recording["filename"])
            srt_path = os.path.splitext(source_path)[0] + ".srt"
            if not os.path.isfile(source_path) or not os.path.isfile(srt_path):
                continue
            output = await edit_recording(
                # Keep the two publish styles in separate namespaces.  The
                # editor's sequence-based filename allocation is not atomic,
                # so concurrent realistic/conservative jobs could otherwise
                # select the same output path.
                source_path, srt_path, room_name=f"publish-variant-{variant}", record_date=(recording["start_time"] or "")[:10].replace("-", ""),
                room_id=recording["room_id"], clip_engine=variant,
            )
            if output:
                generated.append(output)
        if not generated:
            raise RuntimeError("clip engine produced no output")
        output_path = generated[0]
        async with aio_connect() as db:
            await db.execute(f"UPDATE clip_groups SET {status_field}=2, {error_field}=NULL, {output_field}=? WHERE id=?", (output_path, group_id))
            await db.commit()
    except Exception as exc:
        logger.error("%s pipeline group %s failed: %s", variant, group_id, exc)
        async with aio_connect() as db:
            await db.execute(f"UPDATE clip_groups SET {status_field}=-1, {error_field}=? WHERE id=?", (str(exc)[:400], group_id))
            await db.commit()


async def _extract_srt_for_director(group_id: int) -> Optional[str]:
    """Extract combined SRT text for a group (up to 5000 chars)."""
    try:
        async with aio_connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT filename FROM recordings WHERE group_id = ? AND transcribed = 2 AND duration_status = 'accepted' LIMIT 3",
                (group_id,),
            ) as cur:
                rows = await cur.fetchall()
        srt_content = ""
        for r in rows:
            srt_path = os.path.join(RECORDINGS_DIR, os.path.splitext(r["filename"])[0] + ".srt")
            if os.path.exists(srt_path):
                with open(srt_path, encoding="utf-8") as f:
                    srt_content += f.read() + "\n\n"
                if len(srt_content) > 3000:
                    break
        return srt_content[:5000] or None
    except Exception as e:
        logger.error(f"_extract_srt_for_director group {group_id}: {e}")
        return None


async def _get_group_total_duration(group_id: int) -> float:
    """Calculate total duration of all valid recordings in a group.
    Returns 0.0 if no recordings exist or all are invalid."""
    total = 0.0
    try:
        async with aio_connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, filename FROM recordings WHERE group_id = ? AND transcribed = 2 AND local_deleted = 0 AND duration_status = 'accepted'",
                (group_id,),
            ) as cur:
                rows = await cur.fetchall()
        for r in rows:
            mp4_path = os.path.join(RECORDINGS_DIR, r["filename"])
            dur = await _get_video_duration(mp4_path)
            if dur > 0:
                total += dur
    except Exception as e:
        logger.warning(f"_get_group_total_duration group {group_id}: {e}")
    return total


def _pad_video_to_min_duration(out_path: str, current_duration: float, min_duration: float = MIN_FINAL_VIDEO_DURATION, target_duration: float = TARGET_PUBLISH_DURATION) -> Optional[str]:
    """Pad near-threshold videos by cloning the last frame instead of failing.

    Some GPU compositions land at 28-30 seconds because of transition/audio
    rounding. Treat 28s as the business floor, and extend 28s+ outputs to
    TARGET_PUBLISH_DURATION so Douyin's 30s boundary never rejects 29.x clips.
    Returns the usable output path, or None if padding failed or the clip is
    too short to rescue safely.
    """
    if current_duration >= target_duration:
        return out_path
    if current_duration < min_duration:
        return None

    import subprocess as _sp
    from pathlib import Path as _Path

    src = _Path(out_path)
    padded = src.with_name(src.stem + "_padded.mp4")
    pad = max(0.1, target_duration - current_duration)
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-vf", f"tpad=stop_mode=clone:stop_duration={pad:.3f}",
        "-af", f"apad=pad_dur={pad:.3f}",
        "-t", f"{target_duration:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(padded),
    ]
    result = _sp.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not padded.exists() or padded.stat().st_size <= 0:
        logger.warning(
            "Failed to pad near-threshold video %s from %.1fs to %.1fs: %s",
            out_path, current_duration, target_duration, (result.stderr or "")[-300:],
        )
        try:
            padded.unlink(missing_ok=True)
        except Exception:
            pass
        return None

    try:
        src.unlink(missing_ok=True)
    except Exception:
        pass
    return str(padded)


async def _check_group_recordings_exist(group_id: int) -> tuple[bool, list]:
    """Check if all recordings for a group exist on disk.
    Returns (all_exist, list_of_missing_filenames)."""
    missing = []
    try:
        async with aio_connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, filename FROM recordings WHERE group_id = ? AND local_deleted = 0",
                (group_id,),
            ) as cur:
                rows = await cur.fetchall()
        for r in rows:
            mp4_path = os.path.join(RECORDINGS_DIR, r["filename"])
            if not os.path.exists(mp4_path):
                missing.append(f"{r['id']}:{r['filename']}")
    except Exception as e:
        logger.warning(f"_check_group_recordings_exist group {group_id}: {e}")
    return len(missing) == 0, missing


class DirectorPipelineStageTimeout(TimeoutError):
    """Raised when one director pipeline stage exceeds its own deadline."""

    def __init__(self, stage: str, seconds: int):
        self.stage = stage
        self.seconds = seconds
        super().__init__(f"director {stage} timeout ({seconds}s exceeded)")


async def _director_stage(group_id: int, stage: str, awaitable, timeout_seconds: int):
    started = time.monotonic()
    logger.info(f"Director pipeline group {group_id}: {stage} started (timeout={timeout_seconds}s)")
    try:
        result = await asyncio.wait_for(awaitable, timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        elapsed = time.monotonic() - started
        logger.error(f"Director pipeline group {group_id}: {stage} timed out after {elapsed:.1f}s")
        raise DirectorPipelineStageTimeout(stage, timeout_seconds) from exc
    elapsed = time.monotonic() - started
    logger.info(f"Director pipeline group {group_id}: {stage} finished in {elapsed:.1f}s")
    return result


async def _run_director_pipeline(group_id: int):
    """
    Full director pipeline: generate script → match segments → voiceover → compose video.
    Runs independently from the classic pipeline; no fallback to classic on failure.
    At most _DIRECTOR_SEM concurrent pipelines to avoid flooding GPU TTS queue.
    """
    try:
        async with aio_connect() as db:
            from pipeline_state import claim_pipeline_start
            if not await claim_pipeline_start(db, "director_status", group_id):
                logger.info(f"Director pipeline group {group_id} already running/completed — skipping")
                return
            await db.commit()
        # Skip if already completed (e.g. triggered again on restart)
        async with aio_connect() as db:
            async with db.execute(
                "SELECT director_status FROM clip_groups WHERE id = ?", (group_id,)
            ) as cur:
                row = await cur.fetchone()
        if row and row[0] == 2:
            logger.info(f"Director pipeline group {group_id} already complete — skipping")
            return
    except Exception as e:
        logger.error(f"Director pipeline {group_id} pre-check DB error: {e} — will retry inside sem")
        # Don't abort; proceed to semaphore where inner will handle it properly

    async with _DIRECTOR_SEM:
        try:
            await asyncio.wait_for(_run_director_pipeline_inner(group_id), timeout=1800)  # 30 min timeout
        except DirectorPipelineStageTimeout as e:
            logger.error(f"Director pipeline group {group_id} timed out in stage {e.stage} after {e.seconds}s")
            try:
                async with aio_connect() as db:
                    await db.execute(
                        "UPDATE clip_groups SET director_status = -1, director_error = ? WHERE id = ?",
                        (f"{e.stage} timeout ({e.seconds}s exceeded)", group_id),
                    )
                    await db.commit()
            except Exception:
                pass
        except asyncio.TimeoutError:
            logger.error(f"Director pipeline group {group_id} timed out after 30min")
            try:
                async with aio_connect() as db:
                    await db.execute(
                        "UPDATE clip_groups SET director_status = -1, director_error = ? WHERE id = ?",
                        ("pipeline timeout (30min exceeded; last step unknown)", group_id),
                    )
                    await db.commit()
            except Exception:
                pass
        except Exception as e:
            import traceback
            logger.error(f"Director pipeline {group_id} unhandled exception: {e}\n{traceback.format_exc()}")
            try:
                async with aio_connect() as db:
                    await db.execute(
                        "UPDATE clip_groups SET director_status = -1, director_error = ? WHERE id = ?",
                        (str(e)[:400], group_id),
                    )
                    await db.commit()
            except Exception as db_err:
                logger.error(f"Director pipeline {group_id} failed to write error status: {db_err}")


async def _run_director_pipeline_inner(group_id: int):
    import json
    from director_script import DirectorScriptGenerator
    from director_matcher import DirectorMatcher
    from voice_director import VoiceDirector
    from director_video import DirectorVideoComposer

    # Re-check after semaphore (another task may have completed while we waited)
    async with aio_connect() as db:
        async with db.execute(
            "SELECT director_status FROM clip_groups WHERE id = ?", (group_id,)
        ) as cur:
            row = await cur.fetchone()
    if row and row[0] == 2:
        logger.info(f"Director pipeline group {group_id} already complete (post-semaphore check) — skipping")
        return

    # Early check: skip groups without any recordings
    async with aio_connect() as db:
        async with db.execute(
            "SELECT COUNT(*) FROM recordings WHERE group_id = ?",
            (group_id,),
        ) as cur:
            rec_count = (await cur.fetchone())[0]
    if rec_count == 0:
        logger.info(f"Director pipeline group {group_id} has no recordings — skipping")
        async with aio_connect() as db:
            await db.execute(
                "UPDATE clip_groups SET director_status = -2, director_error = 'no recordings in group' WHERE id = ?",
                (group_id,),
            )
            await db.commit()
        return

    # Pre-filter: check if all recording files exist on disk
    all_exist, missing_files = await _check_group_recordings_exist(group_id)
    if not all_exist:
        logger.info(f"Director pipeline group {group_id} skipping: {len(missing_files)} recording files missing")
        async with aio_connect() as db:
            await db.execute(
                "UPDATE clip_groups SET director_status = -2, director_error = ? WHERE id = ?",
                (f'recording files missing ({len(missing_files)}): ' + ', '.join(missing_files[:5]), group_id),
            )
            await db.commit()
        return

    async def _fail(reason: str):
        logger.error(f"Director pipeline group {group_id} failed: {reason}")
        async with aio_connect() as db:
            await db.execute(
                "UPDATE clip_groups SET director_status = -1, director_error = ? WHERE id = ?",
                (reason[:400], group_id),
            )
            await db.commit()

    # The wrapper atomically claimed status=1.
    async with aio_connect() as db:
        await db.execute("UPDATE clip_groups SET director_error = NULL WHERE id = ?", (group_id,))
        await db.commit()

    try:
        # 1. Group metadata
        async with aio_connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT cg.wig_model, cg.wig_color, r.name as room_name
                   FROM clip_groups cg LEFT JOIN rooms r ON cg.room_id = r.id
                   WHERE cg.id = ?""",
                (group_id,),
            ) as cur:
                grp = await cur.fetchone()
        if not grp:
            return await _fail("group not found")

        # 2. SRT content
        srt_content = await _extract_srt_for_director(group_id)
        if not srt_content:
            return await _fail("no SRT content available")

        # 3. Generate script
        script_gen = DirectorScriptGenerator()
        result = await _director_stage(
            group_id,
            "script generation",
            script_gen.generate_script(
                srt_content=srt_content,
                wig_model=grp["wig_model"] or "",
                wig_color=grp["wig_color"] or "",
                room_name=grp["room_name"] or "",
            ),
            180,
        )
        if not result.get("success"):
            # Fallback: use existing director_script from DB if generation fails
            existing_script = None
            try:
                async with aio_connect() as db2:
                    async with db2.execute(
                        "SELECT director_script FROM clip_groups WHERE id = ?", (group_id,)
                    ) as cur2:
                        row2 = await cur2.fetchone()
                    if row2 and row2[0]:
                        import json as _json
                        try:
                            existing_script = _json.loads(row2[0])
                            logger.info(f"Director pipeline group {group_id}: script generation failed ({result.get('error')}), using existing script from DB")
                        except Exception:
                            pass
            except Exception:
                pass
            if existing_script:
                script = existing_script
            elif result.get("script"):
                # The generator returns a validated fallback script together
                # with success=False when the LLM response is malformed.  It
                # is still usable for matching and, importantly, makes the
                # failure visible without leaving the director pipeline stuck.
                script = result["script"]
            else:
                return await _fail(f"script generation: {result.get('error', 'unknown')}")
        else:
            script = result["script"]
        async with aio_connect() as db:
            await db.execute(
                "UPDATE clip_groups SET director_script = ? WHERE id = ?",
                (json.dumps(script), group_id),
            )
            await db.commit()

        # 4. Match segments to recordings
        matcher = DirectorMatcher(DB_PATH)
        script_segments = script.get("scenes") or script.get("segments") or []
        matched_segments = await _director_stage(
            group_id,
            "segment matching",
            matcher.match_segments_to_recordings(script_segments, group_id),
            300,
        )
        if not matched_segments:
            return await _fail(getattr(matcher, "match_error", None) or "segment matching returned empty")

        # 5. Voiceover
        voice_dir = VoiceDirector()
        vo_result = await _director_stage(
            group_id,
            "voiceover",
            voice_dir.generate_voiceover(script=script, group_id=group_id, reference_audio_path=None),
            900,
        )
        if not vo_result.get("success"):
            return await _fail(f"voiceover: {vo_result.get('error', 'unknown')}")
        async with aio_connect() as db:
            await db.execute(
                "UPDATE clip_groups SET director_audio_path = ?, director_segments = ? WHERE id = ?",
                (vo_result.get("merged_audio_path"), json.dumps(vo_result.get("audio_segments", [])), group_id),
            )
            await db.commit()

        # 6. Compose final video
        audio_path = vo_result.get("merged_audio_path")
        
        
        tts_audio_segments = vo_result.get("audio_segments", [])
        config = {
            "video_style": "trendy",
            "script_type": script.get("script_type", "product_showcase"),
            "wig_model": grp["wig_model"] or "",
            "wig_color": grp["wig_color"] or "",
        }
        video_dir = DirectorVideoComposer(RECORDINGS_DIR)
        out_path = await _director_stage(
            group_id,
            "video composition",
            video_dir.compose_final_video(
                matched_segments, audio_path, config, tts_audio_segments=tts_audio_segments
            ),
            1200,
        )
        if not out_path:
            return await _fail("video composition returned no output")

        import subprocess as _sp
        _dur_result = _sp.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", out_path],
            capture_output=True, text=True,
        )
        _dur = float(_dur_result.stdout.strip()) if _dur_result.stdout.strip() else 0.0
        if _dur <= 0:
            return await _fail("导演版视频时长探测失败")
        if _dur < TARGET_PUBLISH_DURATION:
            padded_path = _pad_video_to_min_duration(out_path, _dur)
            if padded_path:
                logger.info(f"Director pipeline group {group_id}: padded video from {_dur:.1f}s to >={TARGET_PUBLISH_DURATION:.1f}s")
                out_path = padded_path
            else:
                try:
                    os.remove(out_path)
                except Exception:
                    pass
                return await _fail(f"导演版视频时长 {_dur:.1f}s < {MIN_FINAL_VIDEO_DURATION:.0f}s 最低要求")

        processed_path = await _director_stage(
            group_id,
            "final video postprocess",
            postprocess_final_video(out_path),
            900,
        )
        if not processed_path:
            return await _fail("导演版4K/50fps背景补齐后处理失败")
        out_path = processed_path

        async with aio_connect() as db:
            await db.execute(
                """UPDATE clip_groups SET
                   merge_status = 2, merged_at = datetime('now'),
                   director_status = 2, director_final_video = ?
                   WHERE id = ?""",
                (out_path, group_id),
            )
            await db.commit()
        logger.info(f"Director pipeline complete for group {group_id}: {os.path.basename(out_path)}")

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"Director pipeline group {group_id} EXCEPTION: {e}\n{tb}")
        await _fail(str(e))


# ── Creative pipeline (自编文案，vibe=creative) ────────────────────────────────


async def _run_creative_pipeline(group_id: int):
    async with _CREATIVE_SEM:
        try:
            await asyncio.wait_for(_run_creative_pipeline_inner(group_id), timeout=1800)  # 30 min timeout
        except asyncio.TimeoutError:
            logger.error(f"Creative pipeline group {group_id} timed out after 30min")
            try:
                async with aio_connect() as db:
                    await db.execute(
                        "UPDATE clip_groups SET creative_status = -1, creative_error = ? WHERE id = ?",
                        ("pipeline timeout (30min exceeded)", group_id),
                    )
                    await db.commit()
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Creative pipeline group {group_id} unhandled: {e}")
            try:
                async with aio_connect() as db:
                    await db.execute(
                        "UPDATE clip_groups SET creative_status = -1, creative_error = ? WHERE id = ?",
                        (str(e)[:400], group_id),
                    )
                    await db.commit()
            except Exception as db_err:
                logger.error(f"Creative pipeline {group_id} failed to write error status: {db_err}")


async def _run_creative_pipeline_inner(group_id: int):
    import json
    from director_script import DirectorScriptGenerator
    from director_matcher import DirectorMatcher
    from voice_director import VoiceDirector
    from director_video import DirectorVideoComposer

    async with aio_connect() as db:
        async with db.execute(
            "SELECT creative_status FROM clip_groups WHERE id = ?", (group_id,)
        ) as cur:
            row = await cur.fetchone()
    if row and row[0] == 2:
        return

    # Early check: skip groups without any recordings
    async with aio_connect() as db:
        async with db.execute(
            "SELECT COUNT(*) FROM recordings WHERE group_id = ?",
            (group_id,),
        ) as cur:
            rec_count = (await cur.fetchone())[0]
    if rec_count == 0:
        logger.info(f"Creative pipeline group {group_id} has no recordings — skipping")
        async with aio_connect() as db:
            await db.execute(
                "UPDATE clip_groups SET creative_status = -2, creative_error = 'no recordings in group' WHERE id = ?",
                (group_id,),
            )
            await db.commit()
        return

    # Pre-filter: check total recording duration before wasting GPU resources.
    # Business rule: ignore unrecoverable <28s material, but allow/pad 28-30s.
    total_dur = await _get_group_total_duration(group_id)
    if 0 < total_dur < MIN_FINAL_VIDEO_DURATION:
        logger.info(f"Creative pipeline group {group_id} skipping: total recording duration {total_dur:.1f}s < {MIN_FINAL_VIDEO_DURATION:.0f}s minimum")
        async with aio_connect() as db:
            await db.execute(
                "UPDATE clip_groups SET creative_status = -2, creative_error = ? WHERE id = ?",
                (f'total recording duration {total_dur:.1f}s < {MIN_FINAL_VIDEO_DURATION:.0f}s minimum', group_id),
            )
            await db.commit()
        return

    async def _fail(reason: str):
        logger.error(f"Creative pipeline group {group_id} failed: {reason}")
        async with aio_connect() as db:
            await db.execute(
                "UPDATE clip_groups SET creative_status = -1, creative_error = ? WHERE id = ?",
                (reason[:400], group_id),
            )
            await db.commit()

    async with aio_connect() as db:
        await db.execute(
            "UPDATE clip_groups SET creative_status = 1, creative_error = NULL WHERE id = ?",
            (group_id,)
        )
        await db.commit()

    try:
        async with aio_connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT cg.wig_model, cg.wig_color, r.name as room_name
                   FROM clip_groups cg LEFT JOIN rooms r ON cg.room_id = r.id
                   WHERE cg.id = ?""",
                (group_id,),
            ) as cur:
                grp = await cur.fetchone()
        if not grp:
            return await _fail("group not found")

        # creative vibe: prompt ignores SRT, passes empty string
        script_gen = DirectorScriptGenerator()
        result = await script_gen.generate_script(
            srt_content="",
            wig_model=grp["wig_model"] or "",
            wig_color=grp["wig_color"] or "",
            room_name=grp["room_name"] or "",
            vibe="creative",
        )
        if not result.get("success"):
            # Fallback: use existing creative_script from DB if generation fails
            existing_script = None
            try:
                async with aio_connect() as db2:
                    async with db2.execute(
                        "SELECT creative_script FROM clip_groups WHERE id = ?", (group_id,)
                    ) as cur2:
                        row2 = await cur2.fetchone()
                    if row2 and row2[0]:
                        import json as _json
                        try:
                            existing_script = _json.loads(row2[0])
                            logger.info(f"Creative pipeline group {group_id}: script generation failed ({result.get('error')}), using existing script from DB")
                        except Exception:
                            pass
            except Exception:
                pass
            if existing_script:
                script = existing_script
            else:
                return await _fail(f"script generation: {result.get('error', 'unknown')}")
        else:
            script = result["script"]
        async with aio_connect() as db:
            await db.execute(
                "UPDATE clip_groups SET creative_script = ? WHERE id = ?",
                (json.dumps(script), group_id),
            )
            await db.commit()

        matcher = DirectorMatcher(DB_PATH)
        script_segments = script.get("scenes") or script.get("segments") or []
        matched_segments = await matcher.match_segments_to_recordings(script_segments, group_id)
        if not matched_segments:
            return await _fail(getattr(matcher, "match_error", None) or "segment matching returned empty")

        voice_dir = VoiceDirector()
        vo_result = await voice_dir.generate_voiceover(script=script, group_id=group_id, reference_audio_path=None)
        if not vo_result.get("success"):
            return await _fail(f"voiceover: {vo_result.get('error', 'unknown')}")
        async with aio_connect() as db:
            await db.execute(
                "UPDATE clip_groups SET creative_audio_path = ? WHERE id = ?",
                (vo_result.get("merged_audio_path"), group_id),
            )
            await db.commit()

        audio_path = vo_result.get("merged_audio_path")
        tts_audio_segments = vo_result.get("audio_segments", [])
        config = {
            "video_style": "trendy",
            "script_type": script.get("script_type", "product_showcase"),
            "wig_model": grp["wig_model"] or "",
            "wig_color": grp["wig_color"] or "",
        }
        video_dir = DirectorVideoComposer(RECORDINGS_DIR)
        out_path = await video_dir.compose_final_video(
            matched_segments, audio_path, config, tts_audio_segments=tts_audio_segments
        )
        if not out_path:
            return await _fail("video composition returned no output")

        import subprocess as _sp
        _dur_result = _sp.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", out_path],
            capture_output=True, text=True,
        )
        _dur = float(_dur_result.stdout.strip()) if _dur_result.stdout.strip() else 0.0
        if _dur <= 0:
            return await _fail("自编版视频时长探测失败")
        if _dur < TARGET_PUBLISH_DURATION:
            padded_path = _pad_video_to_min_duration(out_path, _dur)
            if padded_path:
                logger.info(f"Creative pipeline group {group_id}: padded video from {_dur:.1f}s to >={TARGET_PUBLISH_DURATION:.1f}s")
                out_path = padded_path
            else:
                try:
                    os.remove(out_path)
                except Exception:
                    pass
                return await _fail(f"自编版视频时长 {_dur:.1f}s < {MIN_FINAL_VIDEO_DURATION:.0f}s 最低要求")

        processed_path = await postprocess_final_video(out_path)
        if not processed_path:
            return await _fail("自编版4K/50fps背景补齐后处理失败")
        out_path = processed_path

        async with aio_connect() as db:
            await db.execute(
                "UPDATE clip_groups SET creative_status = 2, creative_final_video = ? WHERE id = ?",
                (out_path, group_id),
            )
            await db.commit()
        logger.info(f"Creative pipeline complete for group {group_id}: {os.path.basename(out_path)}")

    except Exception as e:
        await _fail(str(e))


async def backfill_auto_merge():
    """On startup:
    1. Recover groups that were actively in-progress when the server crashed.
    2. Auto-trigger director+creative pipelines for groups that have classic_status=2
       but never ran director/creative (status=0). This handles groups merged before
       the director/creative pipelines were added.
    """
    try:
        async with aio_connect() as db:
            db.row_factory = aiosqlite.Row
            # Identify groups that were mid-run before resetting them
            async with db.execute("SELECT id FROM clip_groups WHERE classic_status = 1") as cur:
                classic_crashed = [r["id"] for r in await cur.fetchall()]
            async with db.execute("SELECT id FROM clip_groups WHERE director_status = 1") as cur:
                director_crashed = [r["id"] for r in await cur.fetchall()]
            async with db.execute("SELECT id FROM clip_groups WHERE creative_status = 1") as cur:
                creative_crashed = [r["id"] for r in await cur.fetchall()]

            # Reset crashed pipelines back to 0 so they can be re-triggered
            await db.execute("UPDATE clip_groups SET classic_status = 0 WHERE classic_status = 1")
            await db.execute("UPDATE clip_groups SET director_status = 0 WHERE director_status = 1")
            await db.execute("UPDATE clip_groups SET creative_status = 0 WHERE creative_status = 1")
            await db.execute(
                "UPDATE clip_groups SET merge_status = 0 "
                "WHERE merge_status = 1 AND merged_filename IS NULL AND director_final_video IS NULL"
            )
            await db.commit()

        # Only re-trigger the groups that were actually crashed mid-run
        groups = list(set(classic_crashed) | set(director_crashed) | set(creative_crashed))
        if classic_crashed:
            logger.info(f"Backfill: {len(classic_crashed)} classic pipelines crashed, will retry: {classic_crashed}")
        if director_crashed:
            logger.info(f"Backfill: {len(director_crashed)} director pipelines crashed, will retry: {director_crashed}")
        if creative_crashed:
            logger.info(f"Backfill: {len(creative_crashed)} creative pipelines crashed, will retry: {creative_crashed}")

        triggered = 0
        for gid in groups:
            async with aio_connect() as db:
                db.row_factory = aiosqlite.Row
                if await _auto_merge_group(db, gid):
                    triggered += 1
                    await asyncio.sleep(0.5)

        if triggered:
            logger.info(f"Backfill auto-merge: triggered {triggered}/{len(groups)} crash-recovered groups")
        else:
            logger.info("Backfill auto-merge: no crashed pipelines to recover")

        # Phase 2: auto-trigger director+creative for groups that have classic done
        # but never ran the new pipelines (status=0). These are groups merged before
        # director/creative was added. Skip groups with status != 0 to avoid re-running.
        # Also verify recording files actually exist on disk (not just in DB).
        await asyncio.sleep(2)  # let Phase 1 tasks settle
        async with aio_connect() as db:
            db.row_factory = aiosqlite.Row
            # First get candidate groups from DB
            # Exclude -2 (permanently failed: no recordings / duration too short) to avoid infinite re-queue
            async with db.execute(
                """SELECT id FROM clip_groups
                   WHERE classic_status = 2
                     AND director_status IN (0, -1, -3)
                     AND (creative_status IN (0, -1, -3) OR creative_status IS NULL)
                   AND EXISTS (SELECT 1 FROM recordings WHERE recordings.group_id = clip_groups.id AND recordings.local_deleted = 0 AND recordings.clipped = 2 AND recordings.duration_status = 'accepted')
                   ORDER BY id DESC"""
            ) as cur:
                raw_director = [dict(r) for r in await cur.fetchall()]
            
            # Verify files actually exist on disk
            backend_dir = Path(__file__).resolve().parent
            recordings_dir = backend_dir.parent / 'recordings'
            valid_director = []
            for g in raw_director:
                gid = g['id']
                async with db.execute(
                    """SELECT filename FROM recordings 
                       WHERE group_id = ? AND local_deleted = 0 AND clipped = 2
                         AND duration_status = 'accepted'
                       LIMIT 1""", (gid,)
                ) as rcur:
                    rows = await rcur.fetchall()
                    has_mp4 = any((recordings_dir / row['filename']).exists() for row in rows)
                has_srt = bool(await _extract_srt_for_director(gid))
                if has_mp4 and has_srt:
                    valid_director.append(gid)
                else:
                    await db.execute(
                        "UPDATE clip_groups SET director_status = -2, director_error = ? WHERE id = ?",
                        ("no SRT content available", gid),
                    )
            await db.commit()
            
            # Groups where director done but creative not started (must have recordings with valid files)
            # Exclude -2 (permanently failed: no recordings / duration too short) to avoid infinite re-queue
            async with db.execute(
                """SELECT id FROM clip_groups
                   WHERE classic_status = 2
                     AND director_status = 2
                     AND (creative_status IN (0, -1, -3) OR creative_status IS NULL)
                   AND EXISTS (SELECT 1 FROM recordings WHERE recordings.group_id = clip_groups.id AND recordings.local_deleted = 0 AND recordings.clipped = 2 AND recordings.duration_status = 'accepted')
                   ORDER BY id DESC"""
            ) as cur:
                raw_creative = [dict(r) for r in await cur.fetchall()]
            
            # Verify files actually exist on disk
            valid_creative = []
            for g in raw_creative:
                gid = g['id']
                async with db.execute(
                    """SELECT filename FROM recordings 
                       WHERE group_id = ? AND local_deleted = 0 AND clipped = 2
                         AND duration_status = 'accepted'
                       LIMIT 1""", (gid,)
                ) as rcur:
                    rows = await rcur.fetchall()
                    for row in rows:
                        fp = recordings_dir / row['filename']
                        if fp.exists():
                            valid_creative.append(gid)
                            break
            
            pending_director = valid_director
            pending_creative_only = valid_creative
            
            skipped_director = len(raw_director) - len(valid_director)
            skipped_creative = len(raw_creative) - len(valid_creative)
            if skipped_director > 0:
                logger.warning(f"Backfill: skipping {skipped_director} director groups with missing recording/SRT files")
            if skipped_creative > 0:
                logger.warning(f"Backfill: skipping {skipped_creative} creative groups with missing recording files")

        pending = list(set(pending_director) | set(pending_creative_only))

        if pending_director:
            logger.info(f"Backfill: {len(pending_director)} groups with classic done but director/creative not run — scheduling...")
        if pending_creative_only:
            logger.info(f"Backfill: {len(pending_creative_only)} groups with director done but creative not run — scheduling...")

        # Phase 2b: Separate scheduling — director first, creative only after director done
        # This prevents wasting resources on creative groups whose director hasn't finished.
        pending_director_groups = pending_director
        pending_creative_groups = pending_creative_only

        # Phase 3: Reset recently failed director/creative groups and re-queue them.
        # Groups that failed due to GPU issues (composition_no_output, ffmpeg_path_error,
        # script_gen, JSON parse) should be retried after GPU restart.
        # Skip groups that have been failing repeatedly (we track this via error patterns).
        # Only retry if GPU is online — otherwise they'll just fail again.
        from gpu_state import is_online as gpu_is_online
        if gpu_is_online():
            await asyncio.sleep(1)  # let Phase 2 tasks settle
            async with aio_connect() as db:
                db.row_factory = aiosqlite.Row
                # Director groups with common recoverable errors (GPU timeout, ffmpeg path, script gen,
                # segment matching, database locked) — permanently-failures (no SRT, no recordings,
                # duration too short) are excluded from retry.
                async with db.execute(
                    """SELECT id FROM clip_groups
                       WHERE classic_status = 2
                         AND director_status IN (-1, -2)
                         AND (
                             director_error LIKE '%video composition returned no output%'
                             OR director_error LIKE '%expected str, bytes or os.PathLike%'
                             OR director_error LIKE '%script generation:%'
                             OR director_error LIKE '%JSON parse%'
                             OR director_error LIKE '%segment matching%'
                             OR director_error LIKE '%database is locked%'
                             OR director_error IS NULL OR director_error = ''
                         )
                         AND NOT (
                             director_error LIKE '%no SRT content%'
                             OR director_error = 'no recordings in group'
                             OR director_error LIKE '%no recordings in group%'
                             OR director_error LIKE '%duration%'
                         )
                         AND EXISTS (SELECT 1 FROM recordings WHERE recordings.group_id = clip_groups.id)
                       ORDER BY id DESC"""
                ) as cur:
                    retry_director = [r["id"] for r in await cur.fetchall()]
                # Creative groups with common recoverable errors
                # (includes groups where director also failed — creative will re-run after director succeeds)
                # Permanently-failed (no recordings, duration too short) excluded.
                async with db.execute(
                    """SELECT id FROM clip_groups
                       WHERE classic_status = 2
                         AND creative_status IN (-1, -2)
                         AND (
                             creative_error LIKE '%video composition returned no output%'
                             OR creative_error LIKE '%expected str, bytes or os.PathLike%'
                             OR creative_error LIKE '%script generation:%'
                             OR creative_error LIKE '%JSON parse%'
                             OR creative_error LIKE '%segment matching%'
                             OR creative_error LIKE '%database is locked%'
                             OR creative_error IS NULL OR creative_error = ''
                         )
                         AND NOT (
                             creative_error LIKE '%no SRT content%'
                             OR creative_error = 'no recordings in group'
                             OR creative_error LIKE '%no recordings in group%'
                             OR creative_error LIKE '%duration%'
                         )
                         AND EXISTS (SELECT 1 FROM recordings WHERE recordings.group_id = clip_groups.id)
                       ORDER BY id DESC"""
                ) as cur:
                    retry_creative = [r["id"] for r in await cur.fetchall()]

            reset_count = 0
            for gid in retry_director:
                try:
                    async with aio_connect() as db2:
                        await db2.execute(
                            "UPDATE clip_groups SET director_status = 0, director_error = NULL WHERE id = ?",
                            (gid,)
                        )
                        await db2.commit()
                    asyncio.create_task(_run_director_pipeline(gid))
                    reset_count += 1
                    await asyncio.sleep(0.1)
                except Exception as e:
                    logger.warning(f"Backfill: failed to reset director group {gid}: {e}")
            for gid in retry_creative:
                try:
                    async with aio_connect() as db2:
                        await db2.execute(
                            "UPDATE clip_groups SET creative_status = 0, creative_error = NULL WHERE id = ?",
                            (gid,)
                        )
                        await db2.commit()
                    asyncio.create_task(_run_creative_pipeline(gid))
                    reset_count += 1
                    await asyncio.sleep(0.1)
                except Exception as e:
                    logger.warning(f"Backfill: failed to reset creative group {gid}: {e}")

            if reset_count:
                logger.info(f"Backfill Phase 3: reset and re-queued {reset_count} failed groups ({len(retry_director)} director, {len(retry_creative)} creative)")
            else:
                logger.info("Backfill Phase 3: no failed groups to retry")
        else:
            logger.info("Backfill Phase 3: GPU offline — skipping failed group retry")

        # Phase 2c: Schedule director groups first (only if GPU is online)
        if gpu_is_online() and pending_director_groups:
            logger.info(f"Backfill Phase 2c: queuing {len(pending_director_groups)} director groups first")
            for gid in pending_director_groups:
                asyncio.create_task(_run_director_pipeline(gid))
                await asyncio.sleep(0.1)
        elif pending_director_groups:
            logger.info(f"Backfill Phase 2c: GPU offline — skipping {len(pending_director_groups)} director groups")

        # Phase 2d: Schedule creative groups only where director is already done (only if GPU is online)
        if gpu_is_online() and pending_creative_groups:
            logger.info(f"Backfill Phase 2d: queuing {len(pending_creative_groups)} creative groups (director already done)")
            for gid in pending_creative_groups:
                asyncio.create_task(_run_creative_pipeline(gid))
                await asyncio.sleep(0.1)
        elif pending_creative_groups:
            logger.info(f"Backfill Phase 2d: GPU offline — skipping {len(pending_creative_groups)} creative groups")
        else:
            logger.info("Backfill: all groups already have director/creative results or in progress")

        # Phase 2e: Qianchuan was added after some groups had already finished
        # clipping. Do NOT batch-start this on normal backend startup: hotfix #13
        # requires one controlled trial video, and automatic restart backfill can
        # claim hundreds of groups at once. Operators can explicitly enable the
        # legacy batch behavior with QIANCHUAN_BACKFILL_ON_STARTUP=1.
        if os.getenv("QIANCHUAN_BACKFILL_ON_STARTUP") == "1":
            pending_qianchuan = []
            try:
                async with aio_connect() as db:
                    db.row_factory = aiosqlite.Row
                    async with db.execute(
                        """SELECT id FROM clip_groups
                           WHERE classic_status = 2
                             AND qianchuan_status IN (0, -1, -3, -4)
                             AND EXISTS (
                               SELECT 1 FROM recordings
                               WHERE recordings.group_id = clip_groups.id
                                 AND recordings.local_deleted = 0
                                 AND recordings.synced = 1
                                 AND recordings.transcribed = 2
                                 AND (recordings.clipped = 2 OR
                                      (recordings.clipped = -1 AND recordings.clip_error LIKE '%local media execution is disabled: thumbnail generation%'))
                             )
                           ORDER BY id DESC"""
                    ) as cur:
                        pending_qianchuan = [row["id"] for row in await cur.fetchall()]
            except Exception as e:
                logger.error(f"Backfill Phase 2e Qianchuan scan failed: {e}")

            if gpu_is_online() and pending_qianchuan:
                from api_v2 import _run_qianchuan_pipeline
                logger.info(f"Backfill Phase 2e: queuing {len(pending_qianchuan)} Qianchuan groups")
                for gid in pending_qianchuan:
                    asyncio.create_task(_run_qianchuan_pipeline(gid))
                    await asyncio.sleep(0.1)
            elif pending_qianchuan:
                logger.info(f"Backfill Phase 2e: GPU offline — skipping {len(pending_qianchuan)} Qianchuan groups")
        else:
            logger.info("Backfill Phase 2e: Qianchuan startup batch disabled; use manual single-group trigger")

        # Phase 4.5: Handle orphaned -3 status groups (never triggered)
        # These are groups that were created with editing_mode=director but never had their
        # pipeline triggered (likely from an old code path or manual intervention).
        await asyncio.sleep(1)
        orphaned_director = []
        orphaned_creative = []
        cleaned_orphans = 0
        try:
            async with aio_connect() as db:
                db.row_factory = aiosqlite.Row
                # Director orphans: classic done, director=-3, has valid recordings
                async with db.execute(
                    """SELECT id FROM clip_groups
                       WHERE classic_status = 2
                         AND director_status = -3
                         AND EXISTS (SELECT 1 FROM recordings WHERE recordings.group_id = clip_groups.id AND recordings.local_deleted = 0 AND recordings.clipped = 2 AND recordings.duration_status = 'accepted')
                       ORDER BY id DESC"""
                ) as cur:
                    orphaned_director = [r["id"] for r in await cur.fetchall()]
                # Creative orphans: classic done, director done, creative=-3, has valid recordings
                async with db.execute(
                    """SELECT id FROM clip_groups
                       WHERE classic_status = 2
                         AND director_status = 2
                         AND creative_status = -3
                         AND EXISTS (SELECT 1 FROM recordings WHERE recordings.group_id = clip_groups.id AND recordings.local_deleted = 0 AND recordings.clipped = 2 AND recordings.duration_status = 'accepted')
                       ORDER BY id DESC"""
                ) as cur:
                    orphaned_creative = [r["id"] for r in await cur.fetchall()]
                # Clean up truly empty groups (no recordings at all) — set to -2
                async with db.execute(
                    """UPDATE clip_groups SET director_status = -2, director_error = 'no recordings in group'
                       WHERE editing_mode = 'director'
                         AND director_status = -3
                         AND classic_status = 2
                         AND NOT EXISTS (SELECT 1 FROM recordings WHERE recordings.group_id = clip_groups.id AND recordings.local_deleted = 0)"""
                ) as cur:
                    cleaned_orphans += cur.rowcount
                async with db.execute(
                    """UPDATE clip_groups SET creative_status = -2, creative_error = 'no recordings in group'
                       WHERE editing_mode = 'director'
                         AND creative_status = -3
                         AND classic_status = 2
                         AND director_status = 2
                         AND NOT EXISTS (SELECT 1 FROM recordings WHERE recordings.group_id = clip_groups.id AND recordings.local_deleted = 0 AND recordings.clipped = 2)"""
                ) as cur:
                    cleaned_orphans += cur.rowcount
                await db.commit()
        except Exception as e:
            logger.error(f"Backfill Phase 4.5 orphan cleanup error: {e}")

        if cleaned_orphans:
            logger.info(f"Backfill Phase 4.5: cleaned {cleaned_orphans} empty orphan groups")

        # Only re-queue orphans if GPU is online
        if gpu_is_online():
            if orphaned_director:
                logger.info(f"Backfill Phase 4.5: re-queuing {len(orphaned_director)} orphaned director groups (status=-3)")
                for gid in orphaned_director:
                    try:
                        async with aio_connect() as db2:
                            await db2.execute(
                                "UPDATE clip_groups SET director_status = 0, director_error = NULL WHERE id = ?",
                                (gid,)
                            )
                            await db2.commit()
                        asyncio.create_task(_run_director_pipeline(gid))
                        await asyncio.sleep(0.1)
                    except Exception as e:
                        logger.warning(f"Backfill Phase 4.5: failed to reset director orphan group {gid}: {e}")
            if orphaned_creative:
                # Only re-queue creative orphans where director is already done
                valid_orphaned_creative = []
                for gid in orphaned_creative:
                    try:
                        async with aio_connect() as db2:
                            db2.row_factory = aiosqlite.Row
                            async with db2.execute(
                                "SELECT director_status FROM clip_groups WHERE id = ?",
                                (gid,)
                            ) as rcur:
                                row = await rcur.fetchone()
                            if row and row["director_status"] == 2:
                                valid_orphaned_creative.append(gid)
                            else:
                                logger.info(f"Backfill Phase 4.5: skipping creative orphan {gid}, director not done (status={row['director_status'] if row else 'unknown'})")
                    except Exception as e:
                        logger.warning(f"Backfill Phase 4.5: failed to check director status for creative orphan {gid}: {e}")

                if valid_orphaned_creative:
                    logger.info(f"Backfill Phase 4.5: re-queuing {len(valid_orphaned_creative)} valid orphaned creative groups (director done)")
                    for gid in valid_orphaned_creative:
                        try:
                            async with aio_connect() as db2:
                                await db2.execute(
                                    "UPDATE clip_groups SET creative_status = 0, creative_error = NULL WHERE id = ?",
                                    (gid,)
                                )
                                await db2.commit()
                            asyncio.create_task(_run_creative_pipeline(gid))
                            await asyncio.sleep(0.1)
                        except Exception as e:
                            logger.warning(f"Backfill Phase 4.5: failed to reset creative orphan group {gid}: {e}")
        else:
            logger.info("Backfill Phase 4.5: GPU offline — skipping orphan re-queuing")

        # Phase 4: Periodic retry of failed groups (runs every 30 min after backfill completes)
        # Handles groups that failed during backfill execution or failed later.
        async def _periodic_retry():
            while True:
                await asyncio.sleep(1800)  # 30 minutes
                try:
                    async with aio_connect() as db:
                        db.row_factory = aiosqlite.Row
                        async with db.execute(
                            """SELECT id FROM clip_groups
                               WHERE classic_status = 2
                                 AND director_status IN (-1, -2)
                                 AND (
                                     director_error LIKE '%video composition returned no output%'
                                     OR director_error LIKE '%expected str, bytes or os.PathLike%'
                                     OR director_error LIKE '%script generation:%'
                                     OR director_error LIKE '%JSON parse%'
                                     OR director_error LIKE '%segment matching%'
                                     OR director_error LIKE '%database is locked%'
                                     OR director_error IS NULL OR director_error = ''
                                 )
                                 AND NOT (
                                     director_error LIKE '%no SRT content%'
                                     OR director_error = 'no recordings in group'
                                     OR director_error LIKE '%no recordings in group%'
                                     OR director_error LIKE '%duration%'
                                 )
                                 AND EXISTS (SELECT 1 FROM recordings WHERE recordings.group_id = clip_groups.id)
                               ORDER BY id DESC
                               LIMIT 100"""  # batch of 100 per cycle (increased from 20)
                        ) as cur:
                            retry_ids = [r["id"] for r in await cur.fetchall()]
                        if retry_ids:
                            logger.info(f"Periodic retry: found {len(retry_ids)} failed groups, re-queuing...")
                            for gid in retry_ids:
                                try:
                                    async with aio_connect() as db2:
                                        await db2.execute(
                                            "UPDATE clip_groups SET director_status = 0, director_error = NULL WHERE id = ?",
                                            (gid,)
                                        )
                                        await db2.commit()
                                    asyncio.create_task(_run_director_pipeline(gid))
                                except Exception as e:
                                    logger.warning(f"Periodic retry: failed to reset director group {gid}: {e}")

                        # Also retry creative — but ONLY where director is already done
                        async with db.execute(
                            """SELECT id FROM clip_groups
                               WHERE classic_status = 2
                                 AND creative_status IN (-1, -2)
                                 AND director_status = 2
                                 AND (
                                     creative_error LIKE '%video composition returned no output%'
                                     OR creative_error LIKE '%expected str, bytes or os.PathLike%'
                                     OR creative_error LIKE '%script generation:%'
                                     OR creative_error LIKE '%JSON parse%'
                                     OR creative_error LIKE '%segment matching%'
                                     OR creative_error LIKE '%database is locked%'
                                     OR creative_error IS NULL OR creative_error = ''
                                 )
                                 AND NOT (
                                     creative_error LIKE '%no SRT content%'
                                     OR creative_error = 'no recordings in group'
                                     OR creative_error LIKE '%no recordings in group%'
                                     OR creative_error LIKE '%duration%'
                                 )
                                 AND EXISTS (SELECT 1 FROM recordings WHERE recordings.group_id = clip_groups.id)
                               ORDER BY id DESC
                               LIMIT 100"""  # batch of 100 per cycle (increased from 20)
                        ) as cur:
                            retry_creative_ids = [r["id"] for r in await cur.fetchall()]
                        if retry_creative_ids:
                            logger.info(f"Periodic retry: found {len(retry_creative_ids)} creative failed groups (director done), re-queuing...")
                            for gid in retry_creative_ids:
                                try:
                                    async with aio_connect() as db2:
                                        await db2.execute(
                                            "UPDATE clip_groups SET creative_status = 0, creative_error = NULL WHERE id = ?",
                                            (gid,)
                                        )
                                        await db2.commit()
                                    asyncio.create_task(_run_creative_pipeline(gid))
                                except Exception as e:
                                    logger.warning(f"Periodic retry: failed to reset creative group {gid}: {e}")
                except Exception as e:
                    logger.warning(f"Periodic retry error: {e}")

        asyncio.create_task(_periodic_retry())

    except Exception as e:
        logger.error(f"Backfill auto-merge error: {e}")
