import asyncio
import heapq
import logging
import os
import time
from typing import Optional

import aiohttp
import aiosqlite
import httpx

from db import DB_PATH, aio_connect
from editor import edit_recording, edit_recording_multi
from analyzer import analyze_recording
from thumbnail import generate_thumbnail

logger = logging.getLogger(__name__)

GPU_SERVICE_URL = os.environ.get("GPU_SERVICE_URL", "http://10.190.0.203:8877")

MIN_RECORDING_HEIGHT = 720  # recordings below this height are skipped from clip jobs
MIN_RECORDING_DURATION = 30  # recordings shorter than this (seconds) are skipped


async def _get_video_duration(mp4_path: str) -> float:
    """Return the video duration in seconds via ffprobe, or 0 on error."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            mp4_path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        return float(stdout.strip())
    except Exception:
        return 0.0


async def _get_video_height(mp4_path: str) -> int:
    """Return the video height via ffprobe, or 0 on error."""
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
    "blocked_count": 0,         # items blocked by merger on last poll
    "active_job_id": None,      # gpu_job_id currently running on GPU
}

# Event to wake the poll loop immediately (used by the flush endpoint)
_flush_event: asyncio.Event = asyncio.Event()
RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), "..", "recordings")
POLL_INTERVAL = 60  # seconds

# At most 2 director pipelines run concurrently: GPU TTS has Semaphore(1), so >2 concurrent
# pipelines would cause TTS jobs to queue up beyond the polling timeout.
_DIRECTOR_SEM = asyncio.Semaphore(2)

# ── Transcription timing tracker ─────────────────────────────────────────────
_job_submit_times: dict[str, float] = {}   # gpu_job_id → time.time() when submitted
_job_durations: list[float] = []           # recent completed job durations (last 20)
_session_done: int = 0                     # jobs completed since backend start


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
    """Quick MP4 validity check via ffprobe (≤3 s). Returns (ok, error_msg)."""
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
    # Throttled: at most 5 per batch, with a 2s pause between batches, to avoid
    # flooding the queue with hundreds of tasks at startup and pegging local CPU.
    _STARTUP_RECOVERY_BATCH = 5
    try:
        async with aio_connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT id, filename, clip_count FROM recordings "
                "WHERE transcribed=2 AND clipped=0 AND local_deleted=0"
            ) as cur:
                orphaned = await cur.fetchall()
        recoverable = []
        for rec in orphaned:
            mp4_path = os.path.join(RECORDINGS_DIR, rec["filename"])
            srt_path = os.path.splitext(mp4_path)[0] + ".srt"
            if os.path.exists(mp4_path) and os.path.exists(srt_path):
                recoverable.append((rec, mp4_path, srt_path))
            else:
                logger.warning(
                    f"Startup recovery: recording {rec['id']} missing files, skipping "
                    f"(mp4={os.path.exists(mp4_path)}, srt={os.path.exists(srt_path)})"
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
            async with aio_connect() as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM recordings WHERE transcribed = 1 AND gpu_job_id IS NOT NULL"
                ) as cur:
                    pending = await cur.fetchall()
                async with db.execute(
                    """SELECT * FROM recordings
                       WHERE synced = 0 AND transcribed = 0 AND local_deleted = 0
                         AND end_time IS NOT NULL AND end_time != start_time"""
                ) as cur:
                    unsynced = await cur.fetchall()

            _poll_state["last_poll_at"] = time.time()
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
                vram_freed = False  # freed at most once per poll cycle
                for rec in unsynced:
                    if not is_online():
                        logger.debug("GPU went offline mid-upload loop, stopping")
                        break
                    filepath = os.path.join(RECORDINGS_DIR, rec["filename"])
                    if not os.path.exists(filepath):
                        continue
                    result = await maybe_merge_before_upload(rec["room_id"], rec["id"])
                    if result is None:
                        blocked += 1
                        continue
                    upload_path, primary_id = result
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
                            await db.execute(
                                "UPDATE recordings SET synced = 1, transcribed = 1, gpu_job_id = ? WHERE id = ?",
                                (job_id, primary_id),
                            )
                            await db.commit()
                _poll_state["blocked_count"] = blocked

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception(f"Transcription poll error: {e}")

        # Sleep until next interval, but wake immediately if flush_poll() is called
        try:
            await asyncio.wait_for(_flush_event.wait(), timeout=POLL_INTERVAL)
            _flush_event.clear()
        except asyncio.TimeoutError:
            pass


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
        async with aio_connect() as db:
            await db.execute(
                "UPDATE recordings SET transcribed=0, synced=0, gpu_job_id=NULL WHERE id=?",
                (rec["id"],),
            )
            await db.commit()
        return

    if _status_code != 200:
        return

    job = _json
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
            # Trigger smart editing in background
            mp4_path = os.path.join(RECORDINGS_DIR, filename)
            asyncio.create_task(_run_editor(recording_id, mp4_path, local_srt, clip_count=clip_count, broadcast_fn=broadcast_fn))
        else:
            logger.error(f"SRT download failed for {job_id}: {_srt_status}")
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
    if 0 < duration < MIN_RECORDING_DURATION:
        reason = f"录像时长过短（{duration:.0f}秒 < {MIN_RECORDING_DURATION}秒）"
        logger.warning(f"[skip] Recording {recording_id} ({os.path.basename(mp4_path)}): {reason}")
        async with aio_connect() as db:
            await db.execute(
                "UPDATE recordings SET clipped = -1, skip_reason = ? WHERE id = ?",
                (reason, recording_id),
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
            if row and row["value"] in ("legacy", "v2"):
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
                    thumb = await generate_thumbnail(clip_path, offset=offset)
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
        "SELECT classic_status, director_status, creative_status FROM clip_groups WHERE id = ?", (group_id,)
    ) as cur:
        grp = await cur.fetchone()
    if not grp:
        return False

    triggered = False
    if grp["classic_status"] == 0:
        logger.info(f"Auto-triggering classic merge for group {group_id}")
        asyncio.create_task(_merge_group(group_id))
        triggered = True
    if grp["director_status"] == 0:
        logger.info(f"Auto-triggering director pipeline for group {group_id}")
        asyncio.create_task(_run_director_pipeline(group_id))
        triggered = True
    if (grp["creative_status"] or 0) == 0:
        logger.info(f"Auto-triggering creative pipeline for group {group_id}")
        asyncio.create_task(_run_creative_pipeline(group_id))
        triggered = True
    return triggered


async def _extract_srt_for_director(group_id: int) -> Optional[str]:
    """Extract combined SRT text for a group (up to 5000 chars)."""
    try:
        async with aio_connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT filename FROM recordings WHERE group_id = ? AND transcribed = 2 LIMIT 3",
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


async def _run_director_pipeline(group_id: int):
    """
    Full director pipeline: generate script → match segments → voiceover → compose video.
    Runs independently from the classic pipeline; no fallback to classic on failure.
    At most _DIRECTOR_SEM concurrent pipelines to avoid flooding GPU TTS queue.
    """
    # Skip if already completed (e.g. triggered again on restart)
    async with aio_connect() as db:
        async with db.execute(
            "SELECT director_status FROM clip_groups WHERE id = ?", (group_id,)
        ) as cur:
            row = await cur.fetchone()
    if row and row[0] == 2:
        logger.info(f"Director pipeline group {group_id} already complete — skipping")
        return

    async with _DIRECTOR_SEM:
        try:
            await _run_director_pipeline_inner(group_id)
        except Exception as e:
            import traceback
            logger.error(f"Director pipeline {group_id} unhandled exception: {e}\n{traceback.format_exc()}")
            async with aio_connect() as db:
                await db.execute(
                    "UPDATE clip_groups SET director_status = -1, director_error = ? WHERE id = ?",
                    (str(e)[:400], group_id),
                )
                await db.commit()


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

    async def _fail(reason: str):
        logger.error(f"Director pipeline group {group_id} failed: {reason}")
        async with aio_connect() as db:
            await db.execute(
                "UPDATE clip_groups SET director_status = -1, director_error = ? WHERE id = ?",
                (reason[:400], group_id),
            )
            await db.commit()

    # Mark as in-progress
    async with aio_connect() as db:
        await db.execute(
            "UPDATE clip_groups SET director_status = 1, director_error = NULL WHERE id = ?",
            (group_id,)
        )
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
        result = await script_gen.generate_script(
            srt_content=srt_content,
            wig_model=grp["wig_model"] or "",
            wig_color=grp["wig_color"] or "",
            room_name=grp["room_name"] or "",
        )
        if not result.get("success"):
            return await _fail(f"script generation: {result.get('error', 'unknown')}")
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
        matched_segments = await matcher.match_segments_to_recordings(script_segments, group_id)
        if not matched_segments:
            return await _fail("segment matching returned empty")

        # 5. Voiceover
        voice_dir = VoiceDirector()
        vo_result = await voice_dir.generate_voiceover(script=script, group_id=group_id, reference_audio_path=None)
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
        if _dur < 30.0:
            try:
                os.remove(out_path)
            except Exception:
                pass
            return await _fail(f"导演版视频时长 {_dur:.1f}s < 30s 最低要求")

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
        await _fail(str(e))


# ── Creative pipeline (自编文案，vibe=creative) ────────────────────────────────

_creative_sem = asyncio.Semaphore(1)


async def _run_creative_pipeline(group_id: int):
    async with _creative_sem:
        try:
            await _run_creative_pipeline_inner(group_id)
        except Exception as e:
            logger.error(f"Creative pipeline group {group_id} unhandled: {e}")
            async with aio_connect() as db:
                await db.execute(
                    "UPDATE clip_groups SET creative_status = -1, creative_error = ? WHERE id = ?",
                    (str(e)[:400], group_id),
                )
                await db.commit()


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
            return await _fail(f"script generation: {result.get('error', 'unknown')}")
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
            return await _fail("segment matching returned empty")

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
        if _dur < 30.0:
            try:
                os.remove(out_path)
            except Exception:
                pass
            return await _fail(f"自编版视频时长 {_dur:.1f}s < 30s 最低要求")

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
    """On startup, recover only groups that were actively in-progress when the server crashed.
    Do NOT re-trigger all groups with status=0 — that would flood the queue on every restart
    since the default value for new columns is 0."""
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
    except Exception as e:
        logger.error(f"Backfill auto-merge error: {e}")
