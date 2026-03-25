import asyncio
import logging
import os
import aiosqlite
from datetime import datetime
from typing import Dict, Optional

from recorder import RoomRecorder, get_stream_url
from sync import sync_file
from db import DB_PATH

logger = logging.getLogger(__name__)

POLL_INTERVAL = 60  # seconds
AUTO_CLIP_COUNT = 3
MIN_STREAM_HEIGHT = 720   # warn if recorded stream is below this resolution
RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), "..", "recordings")


class MonitorManager:
    def __init__(self, broadcast_fn=None):
        self._recorders: Dict[int, RoomRecorder] = {}
        self._tasks: Dict[int, asyncio.Task] = {}
        self._room_status: Dict[int, str] = {}  # room_id -> live/offline/unknown
        self._resolution_warnings: Dict[int, Optional[str]] = {}  # room_id -> warning or None
        self._broadcast = broadcast_fn  # WebSocket broadcast callback

    async def start_all(self):
        """Load enabled rooms from DB and start monitoring."""
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM rooms WHERE enabled = 1") as cursor:
                rooms = await cursor.fetchall()
        for room in rooms:
            await self.add_room(room["id"], room["name"], room["url"])

    async def add_room(self, room_id: int, name: str, url: str):
        if room_id in self._tasks:
            return
        logger.info(f"Starting monitor for room: {name} ({room_id})")
        task = asyncio.create_task(self._monitor_loop(room_id, name, url))
        self._tasks[room_id] = task

    async def remove_room(self, room_id: int):
        task = self._tasks.pop(room_id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        recorder = self._recorders.pop(room_id, None)
        if recorder:
            await recorder.stop()
        self._room_status.pop(room_id, None)

    def get_status(self, room_id: int) -> dict:
        recorder = self._recorders.get(room_id)
        status = self._room_status.get(room_id, "unknown")
        return {
            "live_status": status,
            "recording": recorder.recording if recorder else False,
            "current_segment": recorder.current_file if recorder else None,
            "segment_start": recorder.segment_start.isoformat() if (recorder and recorder.segment_start) else None,
            "session_start": recorder.session_start.isoformat() if (recorder and recorder.session_start) else None,
            "resolution_warning": self._resolution_warnings.get(room_id),
        }

    async def _check_stream_resolution(self, room_id: int, filename: str):
        """Wait for the recording to accumulate data, then probe its resolution."""
        await asyncio.sleep(20)  # let ffmpeg write enough data for ffprobe
        filepath = os.path.join(RECORDINGS_DIR, filename)
        if not os.path.exists(filepath):
            return
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=p=0", filepath,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate()
            parts = stdout.strip().split(b",")
            if len(parts) >= 2:
                w, h = int(parts[0]), int(parts[1])
                if h < MIN_STREAM_HEIGHT:
                    self._resolution_warnings[room_id] = (
                        f"直播间画质过低：{w}×{h}（低于{MIN_STREAM_HEIGHT}P），"
                        f"录像将被跳过剪辑。请检查直播间画质档位或账号权限。"
                    )
                    logger.warning(f"[room {room_id}] Low resolution stream: {w}x{h}")
                    await self._notify_update(room_id)
                else:
                    self._resolution_warnings.pop(room_id, None)
        except Exception as e:
            logger.debug(f"Resolution check error for {filename}: {e}")

    async def _on_segment_start(self, room_id: int, filename: str, segment_index: int):
        """Called by recorder at the start of each segment — insert DB row with correct filename."""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT OR IGNORE INTO recordings (room_id, filename, start_time, segment_index, clip_count)
                   VALUES (?, ?, ?, ?, ?)""",
                (room_id, filename, datetime.now().isoformat(), segment_index, AUTO_CLIP_COUNT),
            )
            await db.commit()
        # Check stream resolution in background after file has data
        asyncio.create_task(self._check_stream_resolution(room_id, filename))

    async def _on_segment_done(self, room_id: int, filepath: str, segment_index: int):
        """Called when a recording segment completes."""
        import os as _os
        filename = _os.path.basename(filepath)
        size = None
        try:
            size = _os.path.getsize(filepath)
        except Exception:
            pass

        # Persist size and end_time; fetch the recording id
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            await db.execute(
                """UPDATE recordings SET end_time = ?, size_bytes = ?
                   WHERE room_id = ? AND filename = ?""",
                (datetime.now().isoformat(), size, room_id, filename),
            )
            await db.commit()
            async with db.execute(
                "SELECT id FROM recordings WHERE room_id=? AND filename=?",
                (room_id, filename),
            ) as cur:
                rec = await cur.fetchone()

        if not rec:
            await self._notify_update(room_id)
            return

        # Check whether to merge small segments before uploading
        from segment_merger import maybe_merge_before_upload
        result = await maybe_merge_before_upload(room_id, rec["id"])

        if result is None:
            # Small file — deferred until more segments arrive or stream ends
            await self._notify_update(room_id)
            return

        upload_path, primary_id = result

        from comfyui_client import free_vram
        await free_vram()

        job_id = await sync_file(upload_path, room_id)
        if job_id:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE recordings SET synced=1, transcribed=1, gpu_job_id=? WHERE id=?",
                    (job_id, primary_id),
                )
                await db.commit()

        await self._notify_update(room_id)

    async def _monitor_loop(self, room_id: int, name: str, url: str):
        logger.info(f"[{name}] Monitor started")
        while True:
            try:
                stream_url = await get_stream_url(url)
                is_live = stream_url is not None
                prev_status = self._room_status.get(room_id, "unknown")

                if is_live:
                    self._room_status[room_id] = "live"
                    recorder = self._recorders.get(room_id)
                    if not recorder or not recorder.recording:
                        recorder = RoomRecorder(
                            room_id, name, url,
                            on_segment_done=self._on_segment_done,
                            on_segment_start=self._on_segment_start,
                        )
                        self._recorders[room_id] = recorder
                        await recorder.start(stream_url)
                        logger.info(f"[{name}] Recording started")
                else:
                    self._room_status[room_id] = "offline"
                    self._resolution_warnings.pop(room_id, None)
                    recorder = self._recorders.pop(room_id, None)
                    if recorder and recorder.recording:
                        await recorder.stop()
                        logger.info(f"[{name}] Stream ended, recording stopped")

                if prev_status != self._room_status[room_id]:
                    await self._notify_update(room_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[{name}] Monitor error: {e}")

            await asyncio.sleep(POLL_INTERVAL)

        # Cleanup on cancel
        recorder = self._recorders.pop(room_id, None)
        if recorder:
            await recorder.stop()
        logger.info(f"[{name}] Monitor stopped")

    async def _notify_update(self, room_id: int):
        if self._broadcast:
            try:
                await self._broadcast({"type": "status_update", "room_id": room_id})
            except Exception:
                pass
