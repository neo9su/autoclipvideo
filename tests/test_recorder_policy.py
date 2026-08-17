import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from duration_policy import MAX_RECORDING_DURATION_SECONDS, classify_duration
from recorder import RoomRecorder, SEGMENT_DURATION


def test_recorder_boundaries_match_duration_policy():
    assert SEGMENT_DURATION == MAX_RECORDING_DURATION_SECONDS == 2700.0
    assert classify_duration(27.99) == "too_short"
    assert classify_duration(28.0) == "accepted"
    assert classify_duration(2699.99) == "accepted"
    assert classify_duration(2700.0) == "accepted"


def test_ffmpeg_rotation_command_has_exact_45_minute_limit():
    command = RoomRecorder.build_ffmpeg_command("https://stream.invalid/live", "/tmp/room_000.mp4")
    assert float(command[command.index("-t") + 1]) == 2700.0
    assert command[command.index("-c") + 1] == "copy"


def test_short_finalized_segment_is_removed_and_not_dispatched(tmp_path, monkeypatch):
    path = tmp_path / "short.mp4"
    path.write_bytes(b"media")
    dispatched = []

    async def on_done(*args):
        dispatched.append(args)

    recorder = RoomRecorder(1, "room", "https://stream.invalid", on_segment_done=on_done)
    monkeypatch.setattr("recorder.probe_duration", lambda _: asyncio.sleep(0, result=27.99))

    assert asyncio.run(recorder._finalize_segment(str(path), 0)) is False
    assert not path.exists()
    assert dispatched == []


def test_boundary_finalized_segment_is_dispatched(tmp_path, monkeypatch):
    path = tmp_path / "boundary.mp4"
    path.write_bytes(b"media")
    dispatched = []

    async def on_done(*args):
        dispatched.append(args)

    recorder = RoomRecorder(1, "room", "https://stream.invalid", on_segment_done=on_done)
    monkeypatch.setattr("recorder.probe_duration", lambda _: asyncio.sleep(0, result=28.0))

    async def finalize_and_wait():
        assert await recorder._finalize_segment(str(path), 0) is True
        await asyncio.sleep(0)

    asyncio.run(finalize_and_wait())
    assert path.exists()
    assert dispatched == [(1, str(path), 0)]
