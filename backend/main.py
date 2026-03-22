import asyncio
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from typing import Optional, Set

import aiosqlite
import httpx
from datetime import datetime

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from db import init_db, DB_PATH
from models import RoomCreate, Room, Recording, ProductCreate, ProductUpdate, PublishAccountCreate, PublishTaskCreate
from monitor import MonitorManager
from transcribe import poll_transcriptions, _run_editor
from analyzer import merge_group
from sync import sync_file
from thumbnail import generate_thumbnail
from meta_generator import generate_meta, match_product
from publish_scheduler import poll_publish_tasks

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# WebSocket connections
_ws_clients: Set[WebSocket] = set()


async def broadcast(message: dict):
    dead = set()
    for ws in _ws_clients:
        try:
            await ws.send_text(json.dumps(message))
        except Exception:
            dead.add(ws)
    _ws_clients.difference_update(dead)


monitor = MonitorManager(broadcast_fn=broadcast)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await monitor.start_all()
    transcribe_task = asyncio.create_task(poll_transcriptions(broadcast_fn=broadcast))
    scheduler_task = asyncio.create_task(poll_publish_tasks(broadcast_fn=broadcast))
    yield
    transcribe_task.cancel()
    scheduler_task.cancel()
    for t in [transcribe_task, scheduler_task]:
        try:
            await t
        except asyncio.CancelledError:
            pass
    for room_id in list(monitor._tasks.keys()):
        await monitor.remove_room(room_id)


app = FastAPI(title="Douyin Recorder", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Rooms ────────────────────────────────────────────────────────────────────

@app.get("/api/rooms")
async def list_rooms():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM rooms ORDER BY created_at DESC") as cur:
            rows = await cur.fetchall()
    result = []
    for r in rows:
        status = monitor.get_status(r["id"])
        result.append({
            "id": r["id"],
            "name": r["name"],
            "url": r["url"],
            "enabled": bool(r["enabled"]),
            "created_at": r["created_at"],
            **status,
        })
    return result


@app.post("/api/rooms", status_code=201)
async def add_room(body: RoomCreate):
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "INSERT INTO rooms (name, url) VALUES (?, ?)",
                (body.name, body.url)
            )
            await db.commit()
            room_id = cur.lastrowid
        await monitor.add_room(room_id, body.name, body.url)
        return {"id": room_id, "name": body.name, "url": body.url, "enabled": True}
    except aiosqlite.IntegrityError:
        raise HTTPException(status_code=409, detail="Room URL already exists")


@app.delete("/api/rooms/{room_id}", status_code=204)
async def delete_room(room_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM rooms WHERE id = ?", (room_id,))
        await db.commit()
    await monitor.remove_room(room_id)


@app.patch("/api/rooms/{room_id}/toggle")
async def toggle_room(room_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)) as cur:
            room = await cur.fetchone()
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        new_enabled = 0 if room["enabled"] else 1
        await db.execute("UPDATE rooms SET enabled = ? WHERE id = ?", (new_enabled, room_id))
        await db.commit()

    if new_enabled:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)) as cur:
                room = await cur.fetchone()
        await monitor.add_room(room["id"], room["name"], room["url"])
    else:
        await monitor.remove_room(room_id)

    return {"id": room_id, "enabled": bool(new_enabled)}


# ── Recordings ───────────────────────────────────────────────────────────────

@app.post("/api/rooms/{room_id}/upload", status_code=201)
async def upload_recording(room_id: int, file: UploadFile = File(...), srt: Optional[UploadFile] = File(None), duration_sec: Optional[float] = Form(None), clip_count: int = Form(1)):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT id FROM rooms WHERE id = ?", (room_id,)) as cur:
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail="Room not found")

    clip_count = max(1, min(5, clip_count))

    now = datetime.utcnow()
    ts = now.strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r"[^\w\-.]", "_", file.filename or "upload.mp4")
    filename = f"{ts}_{safe_name}"
    recordings_dir = os.path.join(os.path.dirname(__file__), "..", "recordings")
    os.makedirs(recordings_dir, exist_ok=True)
    filepath = os.path.join(recordings_dir, filename)

    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)
    size_bytes = len(content)

    start_time = now.isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO recordings (room_id, filename, start_time, end_time, size_bytes, synced, clip_count) VALUES (?, ?, ?, ?, ?, 0, ?)",
            (room_id, filename, start_time, start_time, size_bytes, clip_count),
        )
        await db.commit()
        recording_id = cur.lastrowid

    asyncio.create_task(_generate_upload_thumb(recording_id, filepath))

    # If SRT is provided, skip GPU transcription and trigger clipping immediately
    if srt is not None:
        srt_filename = os.path.splitext(filename)[0] + ".srt"
        srt_path = os.path.join(recordings_dir, srt_filename)
        srt_content = await srt.read()
        with open(srt_path, "wb") as f:
            f.write(srt_content)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE recordings SET transcribed = 2, synced = 1 WHERE id = ?",
                (recording_id,),
            )
            await db.commit()
        asyncio.create_task(_run_editor(recording_id, filepath, srt_path, clip_duration=duration_sec, clip_count=clip_count))
        return {"id": recording_id, "filename": filename, "size_bytes": size_bytes, "gpu_job_id": None}

    job_id = await sync_file(filepath, room_id)
    if job_id:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE recordings SET transcribed = 1, synced = 1, gpu_job_id = ? WHERE id = ?",
                (job_id, recording_id),
            )
            await db.commit()
    else:
        logger.warning(f"Upload accepted but GPU sync failed for {filename}")

    return {"id": recording_id, "filename": filename, "size_bytes": size_bytes, "gpu_job_id": job_id}


async def _generate_upload_thumb(recording_id: int, mp4_path: str):
    thumb = await generate_thumbnail(mp4_path, offset=5.0)
    if thumb:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE recordings SET thumbnail = ? WHERE id = ?",
                (os.path.relpath(thumb, os.path.join(os.path.dirname(__file__), "..", "recordings")), recording_id),
            )
            await db.commit()


@app.get("/api/rooms/{room_id}/recordings")
async def list_recordings(room_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM recordings WHERE room_id = ? ORDER BY start_time DESC",
            (room_id,)
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


@app.get("/api/recordings")
async def list_all_recordings(page: int = 1, limit: int = 50):
    offset = (page - 1) * limit
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT COUNT(*) FROM recordings") as cur:
            (total,) = await cur.fetchone()
        async with db.execute("""
            SELECT r.*, rm.name as room_name
            FROM recordings r
            JOIN rooms rm ON r.room_id = rm.id
            ORDER BY r.start_time DESC
            LIMIT ? OFFSET ?
        """, (limit, offset)) as cur:
            rows = await cur.fetchall()
    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "pages": max(1, (total + limit - 1) // limit),
    }


@app.get("/api/clips")
async def list_clips():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT r.id, r.filename, r.clip_filename, r.start_time, r.end_time,
                   r.room_id, rm.name as room_name
            FROM recordings r
            JOIN rooms rm ON r.room_id = rm.id
            WHERE r.clipped = 2 AND r.clip_filename IS NOT NULL
            ORDER BY r.start_time DESC
        """) as cur:
            rows = await cur.fetchall()
    items = []
    for r in rows:
        clip_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "recordings", r["clip_filename"])
        )
        size = os.path.getsize(clip_path) if os.path.exists(clip_path) else None
        items.append({**dict(r), "clip_size": size})
    return items


# ── Subtitles ────────────────────────────────────────────────────────────────

@app.get("/api/recordings/{recording_id}/clip")
async def download_clip(recording_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM recordings WHERE id = ?", (recording_id,)) as cur:
            rec = await cur.fetchone()
    if not rec:
        raise HTTPException(status_code=404, detail="Recording not found")
    if rec["clipped"] != 2 or not rec["clip_filename"]:
        raise HTTPException(status_code=404, detail="Clip not ready")
    clip_path = os.path.join(os.path.dirname(__file__), "..", "recordings", rec["clip_filename"])
    if not os.path.exists(clip_path):
        raise HTTPException(status_code=404, detail="Clip file missing")
    return FileResponse(clip_path, media_type="video/mp4", filename=os.path.basename(rec["clip_filename"]))


@app.get("/api/recordings/{recording_id}/clips")
async def list_recording_clips(recording_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM recording_clips WHERE recording_id = ? ORDER BY variant_idx ASC",
            (recording_id,)
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


@app.get("/api/recording-clips/{clip_id}/download")
async def download_recording_clip(clip_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM recording_clips WHERE id = ?", (clip_id,)) as cur:
            clip = await cur.fetchone()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    clip_path = os.path.join(os.path.dirname(__file__), "..", "recordings", clip["clip_filename"])
    if not os.path.exists(clip_path):
        raise HTTPException(status_code=404, detail="Clip file missing")
    return FileResponse(clip_path, media_type="video/mp4", filename=os.path.basename(clip["clip_filename"]))


@app.get("/api/recordings/{recording_id}/thumbnail")
async def get_thumbnail(recording_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT thumbnail FROM recordings WHERE id = ?", (recording_id,)) as cur:
            rec = await cur.fetchone()
    if not rec:
        raise HTTPException(status_code=404, detail="Recording not found")
    if not rec["thumbnail"]:
        raise HTTPException(status_code=404, detail="Thumbnail not available")
    thumb_path = os.path.join(os.path.dirname(__file__), "..", "recordings", rec["thumbnail"])
    if not os.path.exists(thumb_path):
        raise HTTPException(status_code=404, detail="Thumbnail file missing")
    return FileResponse(thumb_path, media_type="image/jpeg")


@app.get("/api/recordings/{recording_id}/srt")
async def download_srt(recording_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM recordings WHERE id = ?", (recording_id,)) as cur:
            rec = await cur.fetchone()
    if not rec:
        raise HTTPException(status_code=404, detail="Recording not found")
    if rec["transcribed"] != 2:
        raise HTTPException(status_code=404, detail="Subtitle not ready")
    srt_filename = os.path.splitext(rec["filename"])[0] + ".srt"
    srt_path = os.path.join(os.path.dirname(__file__), "..", "recordings", srt_filename)
    if not os.path.exists(srt_path):
        raise HTTPException(status_code=404, detail="SRT file missing")
    return FileResponse(srt_path, media_type="text/plain", filename=srt_filename)


# ── Groups ───────────────────────────────────────────────────────────────────

@app.get("/api/groups")
async def list_groups():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT g.*,
                   rm.name as room_name,
                   COUNT(r.id) as clip_count,
                   SUM(CASE WHEN r.clipped = 2 THEN 1 ELSE 0 END) as ready_count
            FROM clip_groups g
            JOIN rooms rm ON g.room_id = rm.id
            LEFT JOIN recordings r ON r.group_id = g.id
            GROUP BY g.id
            ORDER BY g.created_at DESC
        """) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


@app.get("/api/groups/{group_id}")
async def get_group(group_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT g.*, rm.name as room_name FROM clip_groups g JOIN rooms rm ON g.room_id = rm.id WHERE g.id = ?",
            (group_id,)
        ) as cur:
            group = await cur.fetchone()
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")
        async with db.execute(
            """SELECT id, filename, clip_filename, start_time, end_time,
                      session_label, has_tryon, has_promotion, clipped
               FROM recordings WHERE group_id = ? ORDER BY start_time ASC""",
            (group_id,)
        ) as cur:
            recs = await cur.fetchall()
    return {**dict(group), "recordings": [dict(r) for r in recs]}


@app.post("/api/groups/{group_id}/merge")
async def trigger_merge(group_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM clip_groups WHERE id = ?", (group_id,)) as cur:
            group = await cur.fetchone()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    if group["merge_status"] == 1:
        raise HTTPException(status_code=409, detail="Merge already in progress")
    asyncio.create_task(merge_group(group_id))
    return {"group_id": group_id, "merge_status": 1}


@app.get("/api/groups/{group_id}/download")
async def download_merged(group_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM clip_groups WHERE id = ?", (group_id,)) as cur:
            group = await cur.fetchone()
    if not group or group["merge_status"] != 2 or not group["merged_filename"]:
        raise HTTPException(status_code=404, detail="Merged video not ready")
    path = os.path.join(os.path.dirname(__file__), "..", "recordings", group["merged_filename"])
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File missing")
    return FileResponse(path, media_type="video/mp4", filename=group["merged_filename"])


@app.get("/api/recordings/{recording_id}")
async def get_recording(recording_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT r.*, rm.name as room_name FROM recordings r "
            "JOIN rooms rm ON r.room_id = rm.id WHERE r.id = ?",
            (recording_id,)
        ) as cur:
            rec = await cur.fetchone()
    if not rec:
        raise HTTPException(status_code=404, detail="Recording not found")
    return dict(rec)


# ── Retry ────────────────────────────────────────────────────────────────────

@app.post("/api/recordings/{recording_id}/retry-transcribe")
async def retry_transcribe(recording_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM recordings WHERE id = ?", (recording_id,)) as cur:
            rec = await cur.fetchone()
    if not rec:
        raise HTTPException(status_code=404, detail="Recording not found")
    filepath = os.path.join(os.path.dirname(__file__), "..", "recordings", rec["filename"])
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Recording file missing on disk")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE recordings SET transcribed = 0, gpu_job_id = NULL WHERE id = ?",
            (recording_id,)
        )
        await db.commit()
    job_id = await sync_file(filepath, rec["room_id"])
    if job_id:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE recordings SET transcribed = 1, synced = 1, gpu_job_id = ? WHERE id = ?",
                (job_id, recording_id)
            )
            await db.commit()
        return {"recording_id": recording_id, "transcribed": 1}
    raise HTTPException(status_code=500, detail="Failed to submit transcription job")


@app.post("/api/recordings/clip-missing")
async def clip_missing():
    """查找所有已转录但未剪辑的记录，批量发起剪辑任务。"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await db.execute_fetchall(
            "SELECT * FROM recordings WHERE transcribed = 2 AND clipped IN (0, -1)"
        )
    queued, skipped = [], []
    base = os.path.join(os.path.dirname(__file__), "..", "recordings")
    for rec in rows:
        mp4_path = os.path.join(base, rec["filename"])
        srt_path = os.path.join(base, os.path.splitext(rec["filename"])[0] + ".srt")
        if not os.path.exists(mp4_path) or not os.path.exists(srt_path):
            skipped.append(rec["id"])
            continue
        asyncio.create_task(_run_editor(rec["id"], mp4_path, srt_path))
        queued.append(rec["id"])
    return {"queued": queued, "skipped": skipped}


@app.post("/api/recordings/{recording_id}/retry-clip")
async def retry_clip(recording_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM recordings WHERE id = ?", (recording_id,)) as cur:
            rec = await cur.fetchone()
    if not rec:
        raise HTTPException(status_code=404, detail="Recording not found")
    if rec["transcribed"] != 2:
        raise HTTPException(status_code=409, detail="Transcription not complete")
    mp4_path = os.path.join(os.path.dirname(__file__), "..", "recordings", rec["filename"])
    srt_path = os.path.join(
        os.path.dirname(__file__), "..", "recordings",
        os.path.splitext(rec["filename"])[0] + ".srt"
    )
    if not os.path.exists(mp4_path):
        raise HTTPException(status_code=404, detail="Recording file missing")
    if not os.path.exists(srt_path):
        raise HTTPException(status_code=404, detail="SRT file missing")
    asyncio.create_task(_run_editor(recording_id, mp4_path, srt_path))
    return {"recording_id": recording_id, "clipped": 1}


@app.post("/api/recordings/{recording_id}/reveal-clip")
async def reveal_clip(recording_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM recordings WHERE id = ?", (recording_id,)) as cur:
            rec = await cur.fetchone()
    if not rec or rec["clipped"] != 2 or not rec["clip_filename"]:
        raise HTTPException(status_code=404, detail="Clip not found")
    clip_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "recordings", rec["clip_filename"])
    )
    if not os.path.exists(clip_path):
        raise HTTPException(status_code=404, detail="Clip file missing on disk")
    await asyncio.create_subprocess_exec("open", "-R", clip_path)
    return {"ok": True}


# ── Group management ──────────────────────────────────────────────────────────

class GroupCreate(BaseModel):
    room_id: int
    label: str
    wig_model: Optional[str] = None
    wig_color: Optional[str] = None


class GroupUpdate(BaseModel):
    label: str
    wig_model: Optional[str] = None
    wig_color: Optional[str] = None


class RecordingGroupUpdate(BaseModel):
    group_id: Optional[int] = None


@app.post("/api/groups", status_code=201)
async def create_group(body: GroupCreate):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO clip_groups (room_id, label, wig_model, wig_color) VALUES (?, ?, ?, ?)",
            (body.room_id, body.label, body.wig_model or None, body.wig_color or None),
        )
        await db.commit()
        return {"id": cur.lastrowid, "label": body.label,
                "wig_model": body.wig_model, "wig_color": body.wig_color}


@app.patch("/api/groups/{group_id}")
async def update_group(group_id: int, body: GroupUpdate):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id FROM clip_groups WHERE id = ?", (group_id,)) as cur:
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail="Group not found")
        await db.execute(
            "UPDATE clip_groups SET label = ?, wig_model = ?, wig_color = ? WHERE id = ?",
            (body.label, body.wig_model or None, body.wig_color or None, group_id),
        )
        await db.commit()
    return {"id": group_id, "label": body.label,
            "wig_model": body.wig_model, "wig_color": body.wig_color}


@app.delete("/api/recordings/{recording_id}/local-file", status_code=204)
async def delete_local_file(recording_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM recordings WHERE id = ?", (recording_id,)) as cur:
            rec = await cur.fetchone()
    if not rec:
        raise HTTPException(status_code=404, detail="Recording not found")
    if rec["synced"] != 1:
        raise HTTPException(status_code=409, detail="Not synced yet")
    if rec["transcribed"] == 1 or rec["clipped"] == 1:
        raise HTTPException(status_code=409, detail="Processing in progress")
    filepath = os.path.join(os.path.dirname(__file__), "..", "recordings", rec["filename"])
    if os.path.exists(filepath):
        os.unlink(filepath)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE recordings SET local_deleted = 1 WHERE id = ?", (recording_id,))
        await db.commit()


@app.post("/api/cleanup/local-files")
async def bulk_cleanup_local_files():
    """Delete local MP4s for recordings that are fully processed."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM recordings
            WHERE synced = 1
              AND transcribed IN (2, -1)
              AND clipped IN (2, -1)
              AND local_deleted = 0
        """) as cur:
            candidates = await cur.fetchall()
    deleted = 0
    for rec in candidates:
        filepath = os.path.join(os.path.dirname(__file__), "..", "recordings", rec["filename"])
        if os.path.exists(filepath):
            os.unlink(filepath)
            deleted += 1
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE recordings SET local_deleted = 1 WHERE id = ?", (rec["id"],))
            await db.commit()
    return {"deleted": deleted, "total_eligible": len(candidates)}


@app.patch("/api/recordings/{recording_id}/group")
async def reassign_recording_group(recording_id: int, body: RecordingGroupUpdate):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id FROM recordings WHERE id = ?", (recording_id,)) as cur:
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail="Recording not found")
        await db.execute(
            "UPDATE recordings SET group_id = ? WHERE id = ?", (body.group_id, recording_id)
        )
        await db.commit()
    return {"recording_id": recording_id, "group_id": body.group_id}


# ── Reclip ───────────────────────────────────────────────────────────────────

class ReclipRequest(BaseModel):
    room_name: str
    date: str        # "YYYY-MM-DD"
    duration_sec: float
    clip_count: int = 1


@app.post("/api/reclip")
async def reclip(req: ReclipRequest):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT r.* FROM recordings r JOIN rooms rm ON r.room_id = rm.id "
            "WHERE rm.name = ? AND substr(r.start_time,1,10) = ? AND r.transcribed = 2",
            (req.room_name, req.date)
        ) as cur:
            recs = await cur.fetchall()
    if not recs:
        raise HTTPException(status_code=404, detail="No transcribed recordings found")
    queued = []
    for rec in recs:
        mp4_path = os.path.join(os.path.dirname(__file__), "..", "recordings", rec["filename"])
        srt_path = os.path.splitext(mp4_path)[0] + ".srt"
        if os.path.exists(mp4_path) and os.path.exists(srt_path):
            asyncio.create_task(_run_editor(rec["id"], mp4_path, srt_path, clip_duration=req.duration_sec, clip_count=req.clip_count))
            queued.append(rec["id"])
    return {"queued": queued}


# ── GPU Status ────────────────────────────────────────────────────────────────

GPU_SERVICE_URL = os.environ.get("GPU_SERVICE_URL", "http://10.190.0.203:8877")


@app.get("/api/gpu/status")
async def gpu_status():
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            health_r, jobs_r = await asyncio.gather(
                client.get(f"{GPU_SERVICE_URL}/health"),
                client.get(f"{GPU_SERVICE_URL}/jobs"),
            )
        health = health_r.json() if health_r.status_code == 200 else {}
        jobs = jobs_r.json().get("jobs", []) if jobs_r.status_code == 200 else []
    except Exception:
        return {"reachable": False, "health": {}, "jobs": []}

    if jobs:
        job_ids = [j["job_id"] for j in jobs]
        placeholders = ",".join("?" * len(job_ids))
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"SELECT gpu_job_id, filename FROM recordings WHERE gpu_job_id IN ({placeholders})",
                job_ids,
            ) as cur:
                rows = await cur.fetchall()
        id_to_filename = {r["gpu_job_id"]: r["filename"] for r in rows}
        for j in jobs:
            j["filename"] = id_to_filename.get(j["job_id"], "")

    return {"reachable": True, "health": health, "jobs": jobs}


# ── Status ───────────────────────────────────────────────────────────────────

@app.get("/api/status")
async def system_status():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM rooms WHERE enabled = 1") as cur:
            (enabled_rooms,) = await cur.fetchone()
        async with db.execute("SELECT COUNT(*) FROM recordings") as cur:
            (total_recordings,) = await cur.fetchone()
        async with db.execute("SELECT SUM(size_bytes) FROM recordings WHERE size_bytes IS NOT NULL") as cur:
            (total_bytes,) = await cur.fetchone()

    recordings_dir = os.path.join(os.path.dirname(__file__), "..", "recordings")
    local_files = len(os.listdir(recordings_dir)) if os.path.exists(recordings_dir) else 0

    return {
        "enabled_rooms": enabled_rooms,
        "active_recordings": sum(1 for rid in monitor._recorders if monitor._recorders[rid].recording),
        "total_recordings": total_recordings,
        "total_bytes": total_bytes or 0,
        "local_files": local_files,
    }


@app.get("/api/stats")
async def get_stats():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await db.execute_fetchall("""
            SELECT
                SUM(CASE WHEN transcribed = 0 AND synced = 1 THEN 1 ELSE 0 END) AS transcribe_pending,
                SUM(CASE WHEN transcribed = 1 THEN 1 ELSE 0 END)               AS transcribe_running,
                SUM(CASE WHEN transcribed = -1 THEN 1 ELSE 0 END)              AS transcribe_failed,
                SUM(CASE WHEN transcribed = 2 AND clipped = 0 THEN 1 ELSE 0 END) AS clip_pending,
                SUM(CASE WHEN clipped = 1 THEN 1 ELSE 0 END)                   AS clip_running,
                SUM(CASE WHEN clipped = -1 THEN 1 ELSE 0 END)                  AS clip_failed
            FROM recordings
        """)
        r = dict(rows[0])
    return {k: (v or 0) for k, v in r.items()}


# ── WebSocket ────────────────────────────────────────────────────────────────

@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        _ws_clients.discard(websocket)


# ── Products ─────────────────────────────────────────────────────────────────

@app.get("/api/products")
async def list_products(keyword: Optional[str] = None):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if keyword:
            async with db.execute(
                "SELECT * FROM products WHERE product_name LIKE ? OR keywords LIKE ? ORDER BY created_at DESC",
                (f"%{keyword}%", f"%{keyword}%"),
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with db.execute("SELECT * FROM products ORDER BY created_at DESC") as cur:
                rows = await cur.fetchall()
    return [dict(r) for r in rows]


@app.post("/api/products", status_code=201)
async def create_product(body: ProductCreate):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO products (platform, product_id, product_name, product_url, keywords, enabled)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (body.platform, body.product_id, body.product_name,
             body.product_url, body.keywords, int(body.enabled)),
        )
        await db.commit()
    return {"id": cur.lastrowid, **body.model_dump()}


@app.post("/api/products/bulk", status_code=201)
async def bulk_create_products(body: list[ProductCreate]):
    ids = []
    async with aiosqlite.connect(DB_PATH) as db:
        for p in body:
            cur = await db.execute(
                """INSERT INTO products (platform, product_id, product_name, product_url, keywords, enabled)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (p.platform, p.product_id, p.product_name,
                 p.product_url, p.keywords, int(p.enabled)),
            )
            ids.append(cur.lastrowid)
        await db.commit()
    return {"created": len(ids), "ids": ids}


@app.patch("/api/products/{product_id}")
async def update_product(product_id: int, body: ProductUpdate):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id FROM products WHERE id = ?", (product_id,)) as cur:
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail="Product not found")
        updates = {k: v for k, v in body.model_dump().items() if v is not None}
        if not updates:
            return {"id": product_id}
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        await db.execute(
            f"UPDATE products SET {set_clause} WHERE id = ?",
            list(updates.values()) + [product_id],
        )
        await db.commit()
    return {"id": product_id, **updates}


@app.delete("/api/products/{product_id}", status_code=204)
async def delete_product(product_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM products WHERE id = ?", (product_id,))
        await db.commit()


# ── Publish Accounts ──────────────────────────────────────────────────────────

COOKIES_DIR = os.path.expanduser("~/.douyin-publisher/cookies")


@app.get("/api/publish-accounts")
async def list_publish_accounts():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM publish_accounts ORDER BY created_at DESC") as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


@app.post("/api/publish-accounts", status_code=201)
async def create_publish_account(body: PublishAccountCreate):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO publish_accounts (platform, account_name) VALUES (?, ?)",
            (body.platform, body.account_name),
        )
        await db.commit()
        account_id = cur.lastrowid
    return {"id": account_id, "platform": body.platform, "account_name": body.account_name}


@app.delete("/api/publish-accounts/{account_id}", status_code=204)
async def delete_publish_account(account_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM publish_accounts WHERE id = ?", (account_id,))
        await db.commit()


@app.post("/api/publish-accounts/{account_id}/login")
async def login_publish_account(account_id: int):
    """Launch a headed Playwright browser for the user to log in manually."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM publish_accounts WHERE id = ?", (account_id,)) as cur:
            account = await cur.fetchone()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    platform = account["platform"]
    os.makedirs(COOKIES_DIR, exist_ok=True)
    cookie_file = os.path.join(COOKIES_DIR, f"{platform}_{account_id}.json")

    try:
        if platform == "douyin":
            from publisher_douyin import DouyinPublisher
            publisher = DouyinPublisher()
        else:
            raise HTTPException(status_code=400, detail=f"Login not supported for platform: {platform}")

        # Run login in background task so it doesn't block the request
        asyncio.create_task(_do_login(publisher, dict(account), cookie_file, account_id))
        return {"account_id": account_id, "cookie_file": cookie_file, "status": "login_started"}
    except ImportError:
        raise HTTPException(status_code=500, detail="playwright not installed")


async def _do_login(publisher, account: dict, cookie_file: str, account_id: int):
    try:
        success = await publisher.login_interactive(account, cookie_file)
    except Exception as e:
        logger.error(f"_do_login unexpected error: {e}")
        await broadcast({"type": "login_done", "account_id": account_id, "success": False})
        return
    if success:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE publish_accounts SET cookie_file = ? WHERE id = ?",
                (cookie_file, account_id),
            )
            await db.commit()
        await broadcast({"type": "login_done", "account_id": account_id, "success": True})
    else:
        await broadcast({"type": "login_done", "account_id": account_id, "success": False})


# ── Publish Tasks ─────────────────────────────────────────────────────────────

@app.get("/api/publish-tasks")
async def list_publish_tasks(status: Optional[str] = None):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if status:
            async with db.execute(
                """SELECT t.*, g.label as group_label, g.merged_filename,
                          pa.account_name, pa.platform as account_platform,
                          p.product_name
                   FROM publish_tasks t
                   JOIN clip_groups g ON t.group_id = g.id
                   LEFT JOIN publish_accounts pa ON t.account_id = pa.id
                   LEFT JOIN products p ON t.product_id = p.id
                   WHERE t.status = ?
                   ORDER BY t.created_at DESC""",
                (status,),
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with db.execute(
                """SELECT t.*, g.label as group_label, g.merged_filename,
                          pa.account_name, pa.platform as account_platform,
                          p.product_name
                   FROM publish_tasks t
                   JOIN clip_groups g ON t.group_id = g.id
                   LEFT JOIN publish_accounts pa ON t.account_id = pa.id
                   LEFT JOIN products p ON t.product_id = p.id
                   ORDER BY t.created_at DESC"""
            ) as cur:
                rows = await cur.fetchall()
    return [dict(r) for r in rows]


@app.post("/api/publish-tasks", status_code=201)
async def create_publish_task(body: PublishTaskCreate):
    # Validate group exists and has a merged video
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM clip_groups WHERE id = ?", (body.group_id,)) as cur:
            group = await cur.fetchone()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    if group["merge_status"] != 2 or not group["merged_filename"]:
        raise HTTPException(status_code=409, detail="Group merged video not ready (merge_status must be 2)")

    title = body.title
    description = body.description
    tags = body.tags

    # Auto-generate metadata via LLM if requested
    if body.auto_meta:
        meta = await generate_meta(body.group_id)
        if meta:
            title = title or meta.get("title")
            description = description or meta.get("description")
            tags = tags or meta.get("tags")

    video_path = os.path.join(
        os.path.dirname(__file__), "..", "recordings", group["merged_filename"]
    )

    status = "scheduled" if body.scheduled_at else "pending"

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO publish_tasks
               (group_id, platform, account_id, status, scheduled_at,
                title, description, tags, product_id, video_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (body.group_id, body.platform, body.account_id, status,
             body.scheduled_at, title, description, tags,
             body.product_id, video_path),
        )
        await db.commit()
        task_id = cur.lastrowid

    return {
        "id": task_id,
        "group_id": body.group_id,
        "platform": body.platform,
        "status": status,
        "title": title,
        "description": description,
        "tags": tags,
    }


@app.get("/api/publish-tasks/{task_id}")
async def get_publish_task(task_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT t.*, g.label as group_label, g.merged_filename,
                      pa.account_name, p.product_name
               FROM publish_tasks t
               JOIN clip_groups g ON t.group_id = g.id
               LEFT JOIN publish_accounts pa ON t.account_id = pa.id
               LEFT JOIN products p ON t.product_id = p.id
               WHERE t.id = ?""",
            (task_id,),
        ) as cur:
            task = await cur.fetchone()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return dict(task)


@app.delete("/api/publish-tasks/{task_id}", status_code=204)
async def cancel_publish_task(task_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT status FROM publish_tasks WHERE id = ?", (task_id,)) as cur:
            task = await cur.fetchone()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] not in ("pending", "scheduled"):
        raise HTTPException(status_code=409, detail="Can only cancel pending/scheduled tasks")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM publish_tasks WHERE id = ?", (task_id,))
        await db.commit()


@app.post("/api/publish-tasks/{task_id}/retry")
async def retry_publish_task(task_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM publish_tasks WHERE id = ?", (task_id,)) as cur:
            task = await cur.fetchone()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] != "failed":
        raise HTTPException(status_code=409, detail="Can only retry failed tasks")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE publish_tasks SET status = 'pending', error_msg = NULL WHERE id = ?",
            (task_id,),
        )
        await db.commit()
    return {"task_id": task_id, "status": "pending"}


# ── Meta generation ───────────────────────────────────────────────────────────

@app.post("/api/groups/{group_id}/generate-meta")
async def generate_group_meta(group_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT id FROM clip_groups WHERE id = ?", (group_id,)) as cur:
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail="Group not found")
    meta = await generate_meta(group_id)
    if not meta:
        raise HTTPException(status_code=500, detail="LLM metadata generation failed")
    return meta


# ── Product matching ──────────────────────────────────────────────────────────

@app.post("/api/groups/{group_id}/match-product")
async def match_group_product(group_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT id FROM clip_groups WHERE id = ?", (group_id,)) as cur:
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail="Group not found")
    product = await match_product(group_id)
    return {"group_id": group_id, "product": product}


# ── Static frontend ───────────────────────────────────────────────────────────

frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.exists(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
