import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Set

import aiosqlite
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from db import init_db, DB_PATH
from models import RoomCreate, Room, Recording
from monitor import MonitorManager
from transcribe import poll_transcriptions
from analyzer import merge_group
from publisher import generate_publish_content, upload_to_douyin, cookie_file_exists

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
    yield
    transcribe_task.cancel()
    try:
        await transcribe_task
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
async def list_all_recordings():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT r.*, rm.name as room_name
            FROM recordings r
            JOIN rooms rm ON r.room_id = rm.id
            ORDER BY r.start_time DESC
            LIMIT 100
        """) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


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
    return FileResponse(clip_path, media_type="video/mp4", filename=rec["clip_filename"])


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


@app.post("/api/groups/{group_id}/prepare-publish")
async def prepare_publish(group_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM clip_groups WHERE id = ?", (group_id,)) as cur:
            group = await cur.fetchone()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    if group["merge_status"] != 2:
        raise HTTPException(status_code=409, detail="Merged video not ready")

    result = await generate_publish_content(group_id)
    if not result:
        raise HTTPException(status_code=500, detail="Failed to generate publish content")

    title = result.get("title", "")[:20]
    caption = result.get("caption", "")[:150]
    hashtags = result.get("hashtags", [])

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE clip_groups SET
               publish_status = 1, post_title = ?, post_caption = ?, post_hashtags = ?
               WHERE id = ?""",
            (title, caption, json.dumps(hashtags, ensure_ascii=False), group_id),
        )
        await db.commit()

    return {"title": title, "caption": caption, "hashtags": hashtags}


class PublishBody(BaseModel):
    title: str
    caption: str
    hashtags: list[str]


@app.post("/api/groups/{group_id}/publish")
async def publish_group(group_id: int, body: PublishBody):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM clip_groups WHERE id = ?", (group_id,)) as cur:
            group = await cur.fetchone()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    if group["merge_status"] != 2 or not group["merged_filename"]:
        raise HTTPException(status_code=409, detail="Merged video not ready")
    if group["publish_status"] == 2:
        raise HTTPException(status_code=409, detail="Publish already in progress")

    video_path = os.path.join(os.path.dirname(__file__), "..", "recordings", group["merged_filename"])
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Merged video file missing")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE clip_groups SET
               publish_status = 2, post_title = ?, post_caption = ?, post_hashtags = ?
               WHERE id = ?""",
            (body.title[:20], body.caption[:150],
             json.dumps(body.hashtags, ensure_ascii=False), group_id),
        )
        await db.commit()

    asyncio.create_task(
        upload_to_douyin(group_id, video_path, body.title, body.caption, body.hashtags)
    )
    return {"publish_status": 2}


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
        "douyin_cookie_ready": cookie_file_exists(),
    }


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


# ── Static frontend ───────────────────────────────────────────────────────────

frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.exists(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
