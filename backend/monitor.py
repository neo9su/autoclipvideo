import asyncio
import logging
import os
import aiosqlite
from datetime import datetime, timezone
from typing import Dict, Optional

from recorder import RoomRecorder, get_stream_url
from sync import sync_file
from db import DB_PATH, aio_connect
from gpu_execution import reject_local_media

logger = logging.getLogger(__name__)

POLL_INTERVAL = 60  # seconds
AUTO_CLIP_COUNT = 3
MIN_STREAM_HEIGHT = 720   # warn if recorded stream is below this resolution
RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), "..", "recordings")


class MonitorManager:
    def __init__(self, broadcast_fn=None, allow_local_media: bool = False):
        self._recorders: Dict[int, RoomRecorder] = {}
        self._tasks: Dict[int, asyncio.Task] = {}
        self._room_status: Dict[int, str] = {}  # room_id -> live/offline/unknown
        self._resolution_warnings: Dict[int, Optional[str]] = {}  # room_id -> warning or None
        self._last_check_at: Dict[int, datetime] = {}
        self._last_error: Dict[int, Optional[str]] = {}
        self._consecutive_errors: Dict[int, int] = {}
        self._broadcast = broadcast_fn  # WebSocket broadcast callback
        self._allow_local_media = allow_local_media
        self._started_at: Optional[datetime] = None
        self._last_start_error: Optional[str] = None
        self._lifecycle_lock = asyncio.Lock()

    async def start_all(self):
        """Start enabled room monitors on a media-enabled deployment."""
        async with self._lifecycle_lock:
            self._require_media_worker("room monitoring/recording")
            try:
                async with aio_connect() as db:
                    await db.execute(
                        "UPDATE rooms SET enabled = 1 WHERE url != '__custom__' AND enabled != 1"
                    )
                    await db.commit()
                    db.row_factory = aiosqlite.Row
                    async with db.execute(
                        "SELECT * FROM rooms WHERE enabled = 1 AND url != '__custom__'"
                    ) as cursor:
                        rooms = await cursor.fetchall()
                for room in rooms:
                    await self.add_room(room["id"], room["name"], room["url"])
                self._started_at = datetime.now(timezone.utc)
                self._last_start_error = None
            except Exception as exc:
                self._last_start_error = str(exc)[:500]
                raise

    async def stop_all(self) -> None:
        """Stop every room task and recorder managed by this service."""
        for room_id in list(self._tasks):
            await self.remove_room(room_id)

    async def restart(self) -> None:
        """Restart the room monitor service without losing persisted room config."""
        async with self._lifecycle_lock:
            await self.stop_all()
            self._require_media_worker("room monitoring/recording")
            async with aio_connect() as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM rooms WHERE enabled = 1 AND url != '__custom__'"
                ) as cursor:
                    rooms = await cursor.fetchall()
            for room in rooms:
                await self.add_room(room["id"], room["name"], room["url"])
            self._started_at = datetime.now(timezone.utc)
            self._last_start_error = None

    async def get_overall_status(self) -> dict:
        """Return service lifecycle, room, login, and queue health for operators."""
        async with aio_connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT COUNT(*) AS count FROM rooms WHERE enabled = 1") as cursor:
                enabled_rooms = (await cursor.fetchone())["count"]
            async with db.execute(
                """SELECT COUNT(*) AS count FROM recordings
                   WHERE transcribed IN (0, 1) AND local_deleted = 0
                     AND end_time IS NOT NULL AND end_time != start_time"""
            ) as cursor:
                pending_recordings = (await cursor.fetchone())["count"]
            async with db.execute("SELECT COUNT(*) AS count FROM publish_tasks WHERE status IN ('pending', 'publishing', 'scheduled')") as cursor:
                pending_publish = (await cursor.fetchone())["count"]

        task_count = len(self._tasks)
        active_recordings = sum(
            1 for recorder in self._recorders.values() if recorder.recording
        )
        cookie_dir = os.path.expanduser("~/.douyin-publisher/cookies")
        try:
            login_files = os.listdir(cookie_dir) if os.path.isdir(cookie_dir) else []
        except OSError as exc:
            logger.warning("Unable to inspect publisher login state: %s", type(exc).__name__)
            login_files = []
        logged_in = any(name.startswith("douyin_") and name.endswith(".json") for name in login_files)
        return {
            "running": task_count > 0 or self._started_at is not None,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "last_start_error": self._last_start_error,
            "deployment_media_enabled": self._allow_local_media,
            "rooms": {"enabled": enabled_rooms, "monitored": task_count, "recording": active_recordings},
            "login": {"logged_in": logged_in},
            "queue": {"pending_recordings": pending_recordings, "pending_publish": pending_publish},
            "room_status": {str(room_id): self.get_status(room_id) for room_id in self._tasks},
        }

    async def add_room(self, room_id: int, name: str, url: str):
        self._require_media_worker("room monitoring/recording")
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
        self._last_check_at.pop(room_id, None)
        self._last_error.pop(room_id, None)
        self._consecutive_errors.pop(room_id, None)

    def _require_media_worker(self, operation: str) -> None:
        """Keep control-plane instances from accidentally recording locally."""
        if not self._allow_local_media:
            reject_local_media(operation)

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
            "last_check_at": self._last_check_at[room_id].isoformat() if room_id in self._last_check_at else None,
            "last_error": self._last_error.get(room_id),
            "consecutive_errors": self._consecutive_errors.get(room_id, 0),
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
        async with aio_connect() as db:
            await db.execute(
                """INSERT OR IGNORE INTO recordings (room_id, filename, start_time, segment_index, clip_count)
                   VALUES (?, ?, ?, ?, ?)""",
                (room_id, filename, datetime.now().isoformat(), segment_index, AUTO_CLIP_COUNT),
            )
            await db.commit()
        # Check stream resolution in background after file has data
        asyncio.create_task(self._check_stream_resolution(room_id, filename))

    async def _on_segment_rejected(self, room_id: int, filepath: str, segment_index: int, duration):
        """Close the provisional row for a discarded short recording."""
        filename = os.path.basename(filepath)
        from duration_policy import classify_duration, duration_reason
        status = classify_duration(duration)
        async with aio_connect() as db:
            # The start callback is intentionally fire-and-forget. Keep this
            # fallback so a very short segment rejected before that callback
            # commits still leaves only an explicitly deleted/non-valid row.
            await db.execute(
                """INSERT OR IGNORE INTO recordings
                   (room_id, filename, start_time, segment_index, clip_count)
                   VALUES (?, ?, ?, ?, ?)""",
                (room_id, filename, datetime.now().isoformat(), segment_index, AUTO_CLIP_COUNT),
            )
            await db.execute(
                """UPDATE recordings SET end_time=?, size_bytes=0, duration_seconds=?,
                   duration_status=?, skip_reason=?, local_deleted=1
                   WHERE room_id=? AND filename=?""",
                (datetime.now().isoformat(), duration, status, duration_reason(duration), room_id, filename),
            )
            await db.commit()
        await self._notify_update(room_id)

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
        # Use retry logic to handle SQLite database locking
        async def _update_with_retry(db, sql, params, max_retries=3):
            for attempt in range(max_retries):
                try:
                    await db.execute(sql, params)
                    await db.commit()
                    return True
                except Exception as e:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(0.1 * (attempt + 1))
                    else:
                        logger.error(f"Database update failed after {max_retries} retries: {e}")
                        return False
        
        async with aio_connect() as db:
            db.row_factory = aiosqlite.Row
            from duration_policy import classify_duration, probe_duration
            duration = await probe_duration(filepath)
            duration_status = classify_duration(duration)
            await _update_with_retry(
                db,
                """UPDATE recordings SET end_time = ?, size_bytes = ?,
                       duration_seconds = ?, duration_status = ?, skip_reason = NULL
                   WHERE room_id = ? AND filename = ?""",
                (datetime.now().isoformat(), size, duration, duration_status, room_id, filename),
            )
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
            upload_bytes = os.path.getsize(upload_path)
            async with aio_connect() as db:
                await db.execute(
                    """UPDATE recordings SET synced=1, transcribed=1, gpu_job_id=?,
                       transfer_node=?, upload_bytes=? WHERE id=?""",
                    (job_id, "remote-gpu", upload_bytes, primary_id),
                )
                await db.commit()

        await self._notify_update(room_id)

    async def _monitor_loop(self, room_id: int, name: str, url: str):
        logger.info(f"[{name}] Monitor started")
        while True:
            try:
                self._last_check_at[room_id] = datetime.now()
                stream_url = await get_stream_url(url)
                self._last_error[room_id] = None
                self._consecutive_errors[room_id] = 0
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
                            on_segment_rejected=self._on_segment_rejected,
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
                self._last_error[room_id] = str(e)[:500]
                self._consecutive_errors[room_id] = self._consecutive_errors.get(room_id, 0) + 1
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
