"""Tests for resumable batch inventory and bounded remote processing."""
import json
import sqlite3
from pathlib import Path

from scripts.resumable_reclip import discover_pairs, init_db, main, summary


def test_inventory_is_read_only_and_counts_pairs(tmp_path: Path):
    source = tmp_path / "recordings"
    source.mkdir()
    mp4 = source / "good.mp4"
    srt = source / "good.srt"
    mp4.write_bytes(b"source")
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")
    (source / "missing.srt.mp4").write_bytes(b"skip")
    pairs, skipped = discover_pairs(source)
    assert [(item.mp4, item.srt) for item in pairs] == [(mp4, srt)]
    assert skipped == 1
    assert mp4.read_bytes() == b"source"


def test_inventory_creates_checkpoint_and_manifest(tmp_path: Path):
    source = tmp_path / "recordings"
    state = tmp_path / "state"
    source.mkdir()
    (source / "a.mp4").write_bytes(b"video")
    (source / "a.srt").write_text("subtitle", encoding="utf-8")
    assert main(["--source-root", str(source), "--state-dir", str(state)]) == 0
    manifest = (state / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(manifest) == 1
    assert json.loads(manifest[0])["mp4_size"] == 5
    connection = sqlite3.connect(state / "checkpoint.sqlite3")
    assert dict(connection.execute("SELECT status, COUNT(*) FROM items GROUP BY status").fetchall()) == {"pending": 1}
    connection.close()


def test_transport_failures_are_bounded(tmp_path: Path):
    source = tmp_path / "recordings"
    state = tmp_path / "state"
    source.mkdir()
    (source / "a.mp4").write_bytes(b"video")
    (source / "a.srt").write_text("subtitle", encoding="utf-8")
    exit_code = main(["--source-root", str(source), "--state-dir", str(state), "--endpoint", "http://127.0.0.1:1/reclip", "--max-attempts", "1", "--timeout", "1"])
    assert exit_code == 2
    connection = sqlite3.connect(state / "checkpoint.sqlite3")
    assert dict(connection.execute("SELECT status, COUNT(*) FROM items GROUP BY status" ).fetchall()) == {"permanent_failed": 1}
    connection.close()
