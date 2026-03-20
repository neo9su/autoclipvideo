import asyncio
import logging
import aiosqlite
from datetime import datetime
from typing import Dict

from recorder import RoomRecorder, check_live_status, get_stream_url
from sync import sync_file
from db import DB_PATH

logger = logging.getLogger(__name__)

POLL_INTERVAL = 60  # seconds


class MonitorManager:
    def __init__(self, broadcast_fn=None):
        self._recorders: Dict[int, RoomRecorder] = {}
        self._tasks: Dict[int, asyncio.Task] = {}
        self._room_status: Dict[int, str] = {}  # room_id -> live/offline/unknown
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
        }

    async def _on_segment_start(self, room_id: int, filename: str, segment_index: int):
        """Called by recorder at the start of each segment — insert DB row with correct filename."""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT OR IGNORE INTO recordings (room_id, filename, start_time, segment_index)
                   VALUES (?, ?, ?, ?)""",
                (room_id, filename, datetime.now().isoformat(), segment_index),
            )
            await db.commit()

    async def _on_segment_done(self, room_id: int, filepath: str, segment_index: int):
        """Called when a recording segment completes."""
        filename = filepath.split("/")[-1]
        size = None
        try:
            import os
            size = os.path.getsize(filepath)
        except Exception:
            pass

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """UPDATE recordings SET end_time = ?, size_bytes = ?
                   WHERE room_id = ? AND filename = ?""",
                (datetime.now().isoformat(), size, room_id, filename)
            )
            await db.commit()

        # Upload to GPU service (triggers transcription automatically)
        job_id = await sync_file(filepath, room_id)
        if job_id:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    """UPDATE recordings SET synced = 1, transcribed = 1, gpu_job_id = ?
                       WHERE room_id = ? AND filename = ?""",
                    (job_id, room_id, filename)
                )
                await db.commit()

        await self._notify_update(room_id)

    async def _monitor_loop(self, room_id: int, name: str, url: str):
        logger.info(f"[{name}] Monitor started")
        while True:
            try:
                is_live = await check_live_status(url)
                prev_status = self._room_status.get(room_id, "unknown")

                if is_live:
                    self._room_status[room_id] = "live"
                    recorder = self._recorders.get(room_id)
                    if not recorder or not recorder.recording:
                        # Start recording
                        stream_url = await get_stream_url(url)
                        if stream_url:
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
                    recorder = self._recorders.get(room_id)
                    if recorder and recorder.recording:
                        await recorder.stop()
                        self._recorders.pop(room_id, None)
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
