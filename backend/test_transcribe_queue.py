import asyncio
import contextlib
import importlib
import io
import os
import sqlite3
import tempfile
import sys
from datetime import datetime, timedelta
from pathlib import Path

import aiosqlite

sys.path.insert(0, "backend")

import db as dbmod
from db import init_db


def test_asr_profile_is_explicit_and_remote_friendly() -> None:
    sys.path.insert(0, "gpu_service")
    import asr_config

    assert asr_config.ASR_CONFIG.model_name == "large-v3"
    options = asr_config.ASR_CONFIG.transcribe_options()
    assert options["language"] == "zh"
    assert options["beam_size"] >= 5
    assert options["word_timestamps"] is True
    assert "假发" in options["initial_prompt"]
    assert options["condition_on_previous_text"] is False


def _load_backend_main():
    """Import backend.main while hiding optional integration startup warnings."""
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        return importlib.import_module("main")


async def _create_queue_test_db(backend_main, db_path: str) -> None:
    dbmod.DB_PATH = db_path
    backend_main.DB_PATH = db_path
    await init_db()
    async with aiosqlite.connect(db_path) as con:
        await con.execute("INSERT INTO rooms(id, name, url) VALUES(1, 'room', 'https://example.invalid')")
        await con.commit()


async def _insert_recording(db_path: str, **values) -> None:
    defaults = {
        "room_id": 1,
        "filename": "recording.mp4",
        "start_time": datetime.now().isoformat(),
        "end_time": datetime.now().isoformat(),
        "synced": 0,
        "transcribed": 0,
        "local_deleted": 0,
    }
    defaults.update(values)
    columns = ", ".join(defaults)
    placeholders = ", ".join("?" for _ in defaults)
    async with aiosqlite.connect(db_path) as con:
        await con.execute(
            f"INSERT INTO recordings ({columns}) VALUES ({placeholders})",
            list(defaults.values()),
        )
        await con.commit()


async def test_transcribe_queue_excludes_ghost_open_recording(backend_main) -> None:
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(db_path)
    try:
        await _create_queue_test_db(backend_main, db_path)
        started_at = (datetime.now() - timedelta(hours=8)).isoformat()
        await _insert_recording(
            db_path,
            id=101,
            filename="missing_ghost.mp4",
            start_time=started_at,
            end_time=None,
        )

        response = await backend_main.get_transcribe_queue()

        assert response["jobs"] == []
        assert response["total"] == response["session_done"]
    finally:
        Path(db_path).unlink(missing_ok=True)


async def test_transcribe_queue_includes_finished_unsynced_recording_with_file(backend_main) -> None:
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(db_path)
    recordings_dir = Path(backend_main.RECORDINGS_DIR)
    recordings_dir.mkdir(parents=True, exist_ok=True)
    source_path = recordings_dir / "finished_unsynced_queue_test.mp4"
    source_path.write_bytes(b"placeholder")
    try:
        await _create_queue_test_db(backend_main, db_path)
        started_at = (datetime.now() - timedelta(minutes=5)).isoformat()
        ended_at = datetime.now().isoformat()
        await _insert_recording(
            db_path,
            id=102,
            filename=source_path.name,
            start_time=started_at,
            end_time=ended_at,
            size_bytes=source_path.stat().st_size,
        )

        response = await backend_main.get_transcribe_queue()

        assert [job["recording_id"] for job in response["jobs"]] == [102]
        assert response["jobs"][0]["status"] == "待上传"
    finally:
        source_path.unlink(missing_ok=True)
        Path(db_path).unlink(missing_ok=True)


async def test_stale_open_cleanup_keeps_recent_active_recording(backend_main) -> None:
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(db_path)
    try:
        await _create_queue_test_db(backend_main, db_path)
        await _insert_recording(
            db_path,
            id=103,
            filename="recent_active_missing.mp4",
            start_time=datetime.now().isoformat(),
            end_time=None,
        )

        cleaned = await backend_main._cleanup_stale_open_recording_placeholders(max_age_hours=6)

        assert cleaned == 0
        con = sqlite3.connect(db_path)
        row = con.execute("SELECT local_deleted, transcribed FROM recordings WHERE id=103").fetchone()
        con.close()
        assert row == (0, 0)
    finally:
        Path(db_path).unlink(missing_ok=True)


async def main_test() -> None:
    backend_main = _load_backend_main()
    await test_transcribe_queue_excludes_ghost_open_recording(backend_main)
    await test_transcribe_queue_includes_finished_unsynced_recording_with_file(backend_main)
    await test_stale_open_cleanup_keeps_recent_active_recording(backend_main)
    print("transcribe queue ghost-recording guards ok")


if __name__ == "__main__":
    asyncio.run(main_test())
