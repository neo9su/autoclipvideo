import asyncio
import os
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), "..", "recordings")
SEGMENT_DURATION = 25 * 60  # 25 minutes in seconds


from douyin_live import get_stream_url, check_live_status  # noqa: F401


class RoomRecorder:
    def __init__(self, room_id: int, room_name: str, room_url: str, on_segment_done=None, on_segment_start=None):
        self.room_id = room_id
        self.room_name = room_name
        self.room_url = room_url
        self.on_segment_done = on_segment_done    # async callback(room_id, filepath, segment_index)
        self.on_segment_start = on_segment_start  # async callback(room_id, filename, segment_index)
        self.recording = False
        self.current_file: Optional[str] = None
        self.session_start: Optional[datetime] = None
        self.segment_start: Optional[datetime] = None
        self.segment_index = 0
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._task: Optional[asyncio.Task] = None

    def get_segment_filename(self) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{self.room_id}_{ts}_{self.segment_index:03d}.mp4"

    async def start(self, stream_url: str):
        if self.recording:
            return
        self.recording = True
        self.session_start = datetime.now()
        self._task = asyncio.create_task(self._record_loop(stream_url))

    async def stop(self):
        self.recording = False
        last_file = self.current_file  # capture before cleanup
        last_seg_index = self.segment_index
        if self._proc:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=10)
            except Exception:
                self._proc.kill()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._proc = None
        self._task = None
        self.current_file = None
        self.session_start = None
        self.segment_start = None

        # Finalize the last segment that was interrupted by stop()
        if last_file and self.on_segment_done:
            filepath = os.path.join(RECORDINGS_DIR, last_file)
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                logger.info(f"[{self.room_name}] Finalizing last segment on stop: {last_file}")
                asyncio.create_task(
                    self.on_segment_done(self.room_id, filepath, last_seg_index)
                )

    async def _record_loop(self, stream_url: str):
        while self.recording:
            filename = self.get_segment_filename()
            filepath = os.path.join(RECORDINGS_DIR, filename)
            self.current_file = filename
            self.segment_start = datetime.now()

            if self.on_segment_start:
                asyncio.create_task(
                    self.on_segment_start(self.room_id, filename, self.segment_index)
                )

            logger.info(f"[{self.room_name}] Recording segment {self.segment_index}: {filename}")

            cmd = [
                "ffmpeg",
                "-hide_banner", "-loglevel", "warning",
                "-i", stream_url,
                "-c", "copy",
                "-t", str(SEGMENT_DURATION),
                "-movflags", "frag_keyframe+empty_moov+default_base_moof",
                "-y",
                filepath,
            ]

            try:
                self._proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await self._proc.communicate()
                returncode = self._proc.returncode
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[{self.room_name}] ffmpeg error: {e}")
                await asyncio.sleep(5)
                continue

            self._proc = None

            if not self.recording:
                break

            # Segment completed normally
            segment_ok = os.path.exists(filepath) and os.path.getsize(filepath) > 0
            if segment_ok:
                size = os.path.getsize(filepath)
                logger.info(f"[{self.room_name}] Segment done: {filename} ({size // 1024 // 1024}MB)")
                self.segment_index += 1
                if self.on_segment_done:
                    asyncio.create_task(
                        self.on_segment_done(self.room_id, filepath, self.segment_index - 1)
                    )

            if returncode == 0:
                # Re-fetch stream URL for next segment (URL may expire)
                stream_url = await get_stream_url(self.room_url) or stream_url
            else:
                if not segment_ok:
                    logger.warning(f"[{self.room_name}] ffmpeg exited with code {returncode}, retrying in 10s")
                    await asyncio.sleep(10)
                new_url = await get_stream_url(self.room_url)
                if new_url:
                    stream_url = new_url
                else:
                    logger.info(f"[{self.room_name}] Stream ended")
                    self.recording = False
                    break

        self.current_file = None
        self.segment_start = None
        self.recording = False
        logger.info(f"[{self.room_name}] Recording stopped")
