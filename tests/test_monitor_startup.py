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
async def test_gpu_monitor_starts_enabled_room_task(monkeypatch):
    manager = monitor.MonitorManager(allow_local_media=True)

    async def fake_monitor_loop(room_id, name, url):
        await asyncio.sleep(3600)

    monkeypatch.setattr(manager, "_monitor_loop", fake_monitor_loop)
    await manager.add_room(1, "room", "https://live.douyin.com/1")

    assert 1 in manager._tasks
    assert not manager._tasks[1].done()

    await manager.remove_room(1)
