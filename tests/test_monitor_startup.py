import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

import monitor
from gpu_execution import RemoteGpuRequiredError


@pytest.mark.asyncio
async def test_control_plane_monitor_rejects_local_media(monkeypatch):
    manager = monitor.MonitorManager()

    with pytest.raises(RemoteGpuRequiredError):
        await manager.add_room(1, "room", "https://live.douyin.com/1")


@pytest.mark.asyncio
async def test_start_all_enables_recording_rooms_but_skips_custom_upload(monkeypatch, tmp_path):
    db_path = tmp_path / "rooms.db"
    connection = await monitor.aiosqlite.connect(db_path)
    await connection.execute(
        "CREATE TABLE rooms (id INTEGER PRIMARY KEY, name TEXT, url TEXT, enabled INTEGER)"
    )
    await connection.executemany(
        "INSERT INTO rooms (id, name, url, enabled) VALUES (?, ?, ?, ?)",
        [
            (1, "live room", "https://live.douyin.com/1", 0),
            (2, "already enabled", "https://live.douyin.com/2", 1),
            (3, "custom upload", "__custom__", 0),
        ],
    )
    await connection.commit()
    await connection.close()

    monkeypatch.setattr(monitor, "aio_connect", lambda: monitor.aiosqlite.connect(db_path))
    manager = monitor.MonitorManager(allow_local_media=True)
    started = []

    async def fake_add_room(room_id, name, url):
        started.append((room_id, name, url))

    monkeypatch.setattr(manager, "add_room", fake_add_room)
    await manager.start_all()

    assert started == [
        (2, "already enabled", "https://live.douyin.com/2"),
    ]
    async with monitor.aio_connect() as db:
        rows = await db.execute_fetchall("SELECT id, enabled FROM rooms ORDER BY id")
    assert rows == [(1, 0), (2, 1), (3, 0)]


@pytest.mark.asyncio
async def test_gpu_monitor_starts_enabled_room_task(monkeypatch):
    manager = monitor.MonitorManager(allow_local_media=True)

    async def fake_monitor_loop(room_id, name, url):
        await asyncio.sleep(3600)

    monkeypatch.setattr(manager, "_monitor_loop", fake_monitor_loop)
    await manager.add_room(1, "room", "https://live.douyin.com/1")

    assert 1 in manager._tasks
    assert not manager._tasks[1].done()

    await manager.remove_room(1)
