import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from monitor import MonitorManager


def test_status_exposes_monitor_heartbeat_and_retry_state():
    manager = MonitorManager()
    manager._room_status[11] = "offline"
    manager._last_check_at[11] = datetime(2026, 8, 10, 3, 0, 0)
    manager._last_error[11] = "temporary stream lookup failure"
    manager._consecutive_errors[11] = 2

    status = manager.get_status(11)

    assert status["live_status"] == "offline"
    assert status["last_check_at"] == "2026-08-10T03:00:00"
    assert status["last_error"] == "temporary stream lookup failure"
    assert status["consecutive_errors"] == 2


def test_status_defaults_to_unknown_without_a_monitor_check():
    status = MonitorManager().get_status(11)

    assert status["last_check_at"] is None
    assert status["last_error"] is None
    assert status["consecutive_errors"] == 0
