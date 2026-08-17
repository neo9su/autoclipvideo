import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from duration_policy import classify_duration, is_processable_duration
from scripts.inventory_short_recordings import build_inventory


def test_duration_boundaries_are_inclusive_at_28_seconds():
    assert classify_duration(27.9) == "too_short"
    assert classify_duration(27.99) == "too_short"
    assert classify_duration(28.0) == "accepted"
    assert classify_duration(28.01) == "accepted"


def test_invalid_duration_is_unavailable_and_not_processable():
    for value in (None, "", "bad", 0, -1, float("nan"), float("inf"), float("-inf")):
        assert classify_duration(value) == "duration_unavailable"
        assert not is_processable_duration(value)


def test_inventory_is_dry_run_and_only_lists_verified_short_files(tmp_path):
    db_path = tmp_path / "recordings.db"
    media_dir = tmp_path / "recordings"
    media_dir.mkdir()
    short_path = media_dir / "short.mp4"
    short_path.write_bytes(b"short")
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE recordings (id INTEGER, filename TEXT, duration_seconds REAL, size_bytes INTEGER)")
        connection.executemany("INSERT INTO recordings VALUES (?, ?, ?, ?)", [
            (1, "short.mp4", 27.99, 5), (2, "boundary.mp4", 28.0, 10), (3, "unknown.mp4", None, 12),
        ])
    inventory = build_inventory(str(db_path), str(media_dir))
    assert inventory["dry_run"] is True
    assert inventory["count"] == 1
    assert inventory["total_reclaimable_bytes"] == 5
    assert inventory["items"][0]["recording_id"] == 1
    assert json.loads(json.dumps(inventory))["items"][0]["duration_seconds"] == 27.99
    assert short_path.exists()
