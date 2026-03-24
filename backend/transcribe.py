import asyncio
import heapq
import logging
import os
import time
from typing import Optional

import aiosqlite
import httpx

from db import DB_PATH
from editor import edit_recording, edit_recording_multi
from analyzer import analyze_recording
from thumbnail import generate_thumbnail

logger = logging.getLogger(__name__)

GPU_SERVICE_URL = os.environ.get("GPU_SERVICE_URL", "http://10.190.0.203:8877")

# In-memory clip job progress: {recording_id: {"phase": str, "step": int, "total": int, "pct": int, "msg": str}}
_clip_progress: dict = {}
RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), "..", "recordings")
POLL_INTERVAL = 60  # seconds

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

MAX_CONCURRENT_CLIPS = int(os.environ.get("MAX_CONCURRENT_CLIPS", "2"))

_pending_heap: list = []          # heapq of [priority, seq, recording_id]
_pending_meta: dict = {}          # recording_id -> job metadata dict
_running_ids: set = set()         # recording_ids currently executing
_job_seq: int = 0                 # monotonic tie-breaker for same-priority jobs
_dispatch_lock: Optional[asyncio.Lock] = None


def _dispatch_lk() -> asyncio.Lock:
    global _dispatch_lock
    if _dispatch_lock is None:
        _dispatch_lock = asyncio.Lock()
    return _dispatch_lock


async def _try_dispatch():
    """Start queued jobs if slots are available. Called after enqueue and after job completion."""
    to_start = []
    async with _dispatch_lk():
        while _pending_heap and len(_running_ids) < MAX_CONCURRENT_CLIPS:
            entry = heapq.heappop(_pending_heap)
            recording_id = entry[2]
            meta = _pending_meta.pop(recording_id, None)
            if meta is None:
                continue  # was cancelled/removed
            _running_ids.add(recording_id)
            to_start.append((recording_id, meta))

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
    for entry in sorted(_pending_heap):
        priority, seq, recording_id = entry
        meta = _pending_meta.get(recording_id)
        if meta:
            p = _clip_progress.get(recording_id, {})
            queued.append({
                "recording_id": recording_id,
                "status": "queued",
                "priority": meta["priority"],
                "phase": p.get("phase", "queued"),
                "pct": 0,
                "msg": p.get("msg", "排队中"),
                "eta_seconds": None,
                "room_name": meta.get("room_name", ""),
                "record_date": meta.get("record_date", ""),
            })

    return {"running": running, "queued": queued}


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


async def poll_transcriptions(broadcast_fn=None):
    """
    Background loop: poll GPU service for completed transcriptions and retry failed uploads.

    Uses gpu_state.wait_until_online() so the loop wakes up immediately when the GPU
    service comes back online instead of waiting out a fixed sleep interval.
    """
    from gpu_state import is_online, wait_until_online

    while True:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM recordings WHERE transcribed = 1 AND gpu_job_id IS NOT NULL"
                ) as cur:
                    pending = await cur.fetchall()
                async with db.execute(
                    "SELECT * FROM recordings WHERE synced = 0 AND transcribed = 0 AND local_deleted = 0"
                ) as cur:
                    unsynced = await cur.fetchall()

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
                async with httpx.AsyncClient(timeout=10.0) as client:
                    for rec in pending:
                        await _check_job(client, rec, broadcast_fn)

            if is_online():
                from segment_merger import maybe_merge_before_upload
                from sync import sync_file
                from comfyui_client import free_vram
                for rec in unsynced:
                    if not is_online():
                        logger.debug("GPU went offline mid-upload loop, stopping")
                        break
                    filepath = os.path.join(RECORDINGS_DIR, rec["filename"])
                    if not os.path.exists(filepath):
                        continue
                    result = await maybe_merge_before_upload(rec["room_id"], rec["id"])
                    if result is None:
                        continue
                    upload_path, primary_id = result
                    logger.info(f"Uploading {os.path.basename(upload_path)} to GPU service")
                    await free_vram()
                    job_id = await sync_file(upload_path, rec["room_id"])
                    if job_id:
                        _job_submit_times[job_id] = time.time()
                        async with aiosqlite.connect(DB_PATH) as db:
                            await db.execute(
                                "UPDATE recordings SET synced = 1, transcribed = 1, gpu_job_id = ? WHERE id = ?",
                                (job_id, primary_id),
                            )
                            await db.commit()

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Transcription poll error: {e}")

        await asyncio.sleep(POLL_INTERVAL)


async def _check_job(client: httpx.AsyncClient, rec, broadcast_fn):
    job_id = rec["gpu_job_id"]
    try:
        resp = await client.get(f"{GPU_SERVICE_URL}/jobs/{job_id}")
    except Exception as e:
        logger.warning(f"Cannot reach GPU service for job {job_id}: {e}")
        return

    if resp.status_code == 404:
        # GPU service restarted and lost this job — re-queue for upload
        logger.warning(f"Job {job_id} not found on GPU service (restarted?), re-queuing")
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE recordings SET transcribed=0, synced=0, gpu_job_id=NULL WHERE id=?",
                (rec["id"],),
            )
            await db.commit()
        return

    if resp.status_code != 200:
        return

    job = resp.json()
    if job["status"] == "done":
        global _session_done
        if job_id in _job_submit_times:
            dur = time.time() - _job_submit_times.pop(job_id)
            _job_durations.append(dur)
            if len(_job_durations) > 20:
                _job_durations.pop(0)
        _session_done += 1
        await _fetch_srt(client, rec["id"], job_id, rec["filename"], clip_count=rec["clip_count"] if "clip_count" in rec.keys() else 1, broadcast_fn=broadcast_fn)
        if broadcast_fn:
            try:
                await broadcast_fn({"type": "transcribed", "recording_id": rec["id"]})
            except Exception:
                pass
    elif job["status"] == "error":
        err_msg = (job.get("error") or "GPU 转录失败（未知错误）")[:300]
        logger.error(f"GPU transcription error for {rec['filename']}: {err_msg}")
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE recordings SET transcribed = -1, transcribe_error = ? WHERE id = ?",
                (err_msg, rec["id"]),
            )
            await db.commit()


async def _fetch_srt(client: httpx.AsyncClient, recording_id: int, job_id: str, filename: str, clip_count: int = 1, broadcast_fn=None):
    srt_filename = os.path.splitext(filename)[0] + ".srt"
    local_srt = os.path.join(RECORDINGS_DIR, srt_filename)
    try:
        resp = await client.get(
            f"{GPU_SERVICE_URL}/jobs/{job_id}/srt",
            timeout=30.0,
        )
        if resp.status_code == 200:
            with open(local_srt, "wb") as f:
                f.write(resp.content)
            logger.info(f"SRT fetched: {srt_filename}")
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE recordings SET transcribed = 2 WHERE id = ?", (recording_id,)
                )
                await db.commit()
            # Trigger smart editing in background
            mp4_path = os.path.join(RECORDINGS_DIR, filename)
            asyncio.create_task(_run_editor(recording_id, mp4_path, local_srt, clip_count=clip_count, broadcast_fn=broadcast_fn))
        else:
            logger.error(f"SRT download failed for {job_id}: {resp.status_code}")
    except Exception as e:
        logger.error(f"SRT fetch error for {job_id}: {e}")


async def _run_editor(recording_id: int, mp4_path: str, srt_path: str, clip_duration: Optional[float] = None, clip_count: int = 1, broadcast_fn=None):
    """Enqueue a clip job into the priority queue and dispatch if a slot is free."""
    global _job_seq

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE recordings SET clipped = 1 WHERE id = ?", (recording_id,)
        )
        await db.commit()

    # Fetch room info for display in queue
    room_name, record_date = "unknown", ""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
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


async def _do_edit(recording_id: int, mp4_path: str, srt_path: str, clip_duration: Optional[float], clip_count: int, broadcast_fn):
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
        # Fetch room name and recording date for organised output path
        room_name = "unknown"
        date_str = ""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT r.start_time, rm.name as room_name "
                    "FROM recordings r JOIN rooms rm ON r.room_id = rm.id WHERE r.id = ?",
                    (recording_id,)
                ) as cur:
                    info = await cur.fetchone()
            if info:
                room_name = info["room_name"] or "unknown"
                date_str = (info["start_time"] or "")[:10].replace("-", "")
        except Exception as e:
            logger.warning(f"Could not fetch room info for recording {recording_id}: {e}")

        clip_count = max(1, min(5, clip_count))

        if clip_count == 1:
            clip_path = await edit_recording(mp4_path, srt_path, room_name=room_name, record_date=date_str, clip_duration=clip_duration, on_progress=_on_progress)
            clip_paths = [clip_path] if clip_path else []
        else:
            clip_paths = await edit_recording_multi(mp4_path, srt_path, count=clip_count, room_name=room_name, record_date=date_str, clip_duration=clip_duration, on_progress=_on_progress)

        if clip_paths:
            c_dur = clip_duration or 30.0
            async with aiosqlite.connect(DB_PATH) as db:
                for k, clip_path in enumerate(clip_paths):
                    clip_filename = os.path.relpath(clip_path, RECORDINGS_DIR)
                    offset = max(3.0, c_dur * (0.2 + 0.3 * k))
                    thumb = await generate_thumbnail(clip_path, offset=offset)
                    thumb_basename = os.path.relpath(thumb, RECORDINGS_DIR) if thumb else None

                    if k == 0:
                        await db.execute(
                            "UPDATE recordings SET clipped = 2, clip_filename = ?, thumbnail = ? WHERE id = ?",
                            (clip_filename, thumb_basename, recording_id),
                        )

                    await db.execute(
                        "INSERT INTO recording_clips (recording_id, variant_idx, clip_filename, thumbnail) VALUES (?, ?, ?, ?)",
                        (recording_id, k, clip_filename, thumb_basename),
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
        else:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE recordings SET clipped = -1 WHERE id = ?", (recording_id,)
                )
                await db.commit()
            _clip_progress.pop(recording_id, None)
    except Exception as e:
        logger.error(f"Editor failed for recording {recording_id}: {e}")
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE recordings SET clipped = -1 WHERE id = ?", (recording_id,)
            )
            await db.commit()
        _clip_progress.pop(recording_id, None)
