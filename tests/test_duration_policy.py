import sys
import json
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
from duration_policy import (
    MAX_RECORDING_DURATION_SECONDS,
    MIN_RECORDING_DURATION_SECONDS,
    PUBLISH_MAX_DURATION_SECONDS,
    PUBLISH_MIN_DURATION_SECONDS,
    classify_duration,
    is_processable_duration,
    is_within_recording_limit,
)
from scripts.inventory_short_recordings import build_inventory


def test_duration_boundaries():
    assert classify_duration(27.9) == "too_short"
    assert classify_duration(27.99) == "too_short"
    assert classify_duration(28.0) == "accepted"
    assert classify_duration(28.01) == "accepted"


def test_recording_policy_boundaries():
    assert MIN_RECORDING_DURATION_SECONDS == 28.0
    assert MAX_RECORDING_DURATION_SECONDS == 2700.0
    assert classify_duration(2699.99) == "accepted"
    assert classify_duration(2700.0) == "accepted"
    assert is_within_recording_limit(2699.99)
    assert is_within_recording_limit(2700.0)
    assert not is_within_recording_limit(2700.01)


def test_recording_policy_rejects_non_finite_segment_durations():
    assert not is_within_recording_limit(None)
    assert not is_within_recording_limit(float("nan"))
    assert not is_within_recording_limit(float("inf"))


def test_segment_rotation_configuration_is_bounded_at_45_minutes():
    sys.path.insert(0, str(PROJECT_ROOT / "backend"))
    from recorder import SEGMENT_DURATION

    assert SEGMENT_DURATION == MAX_RECORDING_DURATION_SECONDS


def test_invalid_duration_is_unavailable_and_not_processable():
    for value in (None, "", "bad", 0, -1, float("nan"), float("inf"), float("-inf")):
        assert classify_duration(value) == "duration_unavailable"
        assert not is_processable_duration(value)


def test_publish_duration_policy_accepts_legacy_overage_and_rejects_above_new_limit():
    assert PUBLISH_MIN_DURATION_SECONDS == 15.0
    assert PUBLISH_MAX_DURATION_SECONDS == 300.0
    assert PUBLISH_MIN_DURATION_SECONDS <= 162.8 <= PUBLISH_MAX_DURATION_SECONDS
    assert 150.0 < 162.8 < 300.0


def test_inventory_is_dry_run_and_only_lists_verified_short_files(tmp_path, monkeypatch):
    db_path = tmp_path / "recordings.db"
    media_dir = tmp_path / "recordings"
    media_dir.mkdir()
    short_path = media_dir / "short.mp4"
    short_path.write_bytes(b"short")
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE recordings (id INTEGER, filename TEXT, duration_seconds REAL, size_bytes INTEGER)"
    )
    connection.executemany(
        "INSERT INTO recordings VALUES (?, ?, ?, ?)",
        [(1, "short.mp4", 27.99, 5), (2, "boundary.mp4", 28.0, 10), (3, "unknown.mp4", None, 12)],
    )
    connection.commit()
    connection.close()

    class Probe:
        stdout = "27.99\n"

    monkeypatch.setattr("scripts.inventory_short_recordings.subprocess.run", lambda *args, **kwargs: Probe())

    inventory = build_inventory(str(db_path), str(media_dir))

    assert inventory["dry_run"] is True
    assert inventory["count"] == 1
    assert inventory["total_reclaimable_bytes"] == 5
    assert inventory["items"][0]["recording_id"] == 1
    assert json.loads(json.dumps(inventory))["items"][0]["duration_seconds"] == 27.99
    assert short_path.exists()
