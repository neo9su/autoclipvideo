import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from backend import monitor as monitor_module


@pytest.mark.asyncio
async def test_start_all_recreates_enabled_room_tasks(monkeypatch):
    manager = monitor_module.MonitorManager()
    added = []

    class Cursor:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def fetchall(self):
            return [
                {"id": 11, "name": "room-a", "url": "https://example.invalid/a"},
                {"id": 12, "name": "room-b", "url": "https://example.invalid/b"},
            ]

    class Connection:
        row_factory = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        def execute(self, query):
            assert "enabled = 1" in query
            return Cursor()

    async def fake_add_room(room_id, name, url):
        added.append((room_id, name, url))

    monkeypatch.setattr(monitor_module, "aio_connect", lambda: Connection())
    monkeypatch.setattr(manager, "add_room", fake_add_room)

    await manager.start_all()

    assert added == [
        (11, "room-a", "https://example.invalid/a"),
        (12, "room-b", "https://example.invalid/b"),
    ]


def test_status_exposes_monitor_health_fields():
    manager = monitor_module.MonitorManager()
    manager._room_status[11] = "offline"
    manager._last_check_at[11] = monitor_module.datetime(2026, 8, 10, 3, 0, 0)
    manager._last_error[11] = None
    manager._consecutive_errors[11] = 0

    status = manager.get_status(11)

    assert status["live_status"] == "offline"
    assert status["last_check_at"] == "2026-08-10T03:00:00"
    assert status["last_error"] is None
    assert status["consecutive_errors"] == 0
