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
from transcribe import classify_transcription_record


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


def test_transcription_queue_classifier_covers_submission_blockers() -> None:
    base = {
        "transcribed": 0,
        "synced": 0,
        "local_deleted": 0,
        "start_time": "2026-08-21T00:00:00",
        "end_time": "2026-08-21T00:01:00",
        "duration_status": "accepted",
    }
    assert classify_transcription_record(base, media_exists=True, gpu_online=True) == "ready_to_submit"
    assert classify_transcription_record({**base, "duration_status": "too_short"}, media_exists=True, gpu_online=True) == "duration_invalid"
    assert classify_transcription_record({**base, "end_time": None}, media_exists=True, gpu_online=True) == "end_time_invalid"
    assert classify_transcription_record(base, media_exists=False, gpu_online=True) == "media_missing"
    assert classify_transcription_record(base, media_exists=True, gpu_online=True, merge_blocked=True) == "merge_blocked"
    assert classify_transcription_record(base, media_exists=True, gpu_online=False) == "gpu_offline_or_error"
    assert classify_transcription_record({**base, "gpu_job_id": "job-1", "synced": 1, "transcribed": 1}, media_exists=True, gpu_online=True) == "gpu_job_running"
    assert classify_transcription_record({**base, "transcribed": 2}, media_exists=True, gpu_online=True) == "transcription_complete"


def test_upload_preflight_does_not_require_a_local_srt() -> None:
    source = Path("backend/segment_merger.py").read_text()
    function = source[source.index("async def maybe_merge_before_upload"):]
    assert "SRT is not required before upload" in function
    assert "resolve_srt_path" not in function
    assert "empty file" in function


def test_poll_upload_path_validates_mp4_before_sync_and_keeps_failed_uploads_pending() -> None:
    source = Path("backend/transcribe.py").read_text()
    upload_block = source[source.index("result = await maybe_merge_before_upload"):source.index("_poll_state[\"blocked_count\"]")]
    assert "valid, err_msg = await _validate_mp4(upload_path)" in upload_block
    assert "job_id = await sync_file(upload_path, rec[\"room_id\"])" in upload_block
    assert "GPU upload did not return a job" in upload_block
    assert "transcribed = 1" in upload_block


def test_remote_upload_rejects_empty_sources_and_exposes_cache_invalidation() -> None:
    source = Path("backend/sync.py").read_text()
    assert "input_bytes <= 0" in source
    assert "def forget_upload_job" in source
    assert "X-Idempotency-Key" in source


def test_queue_diagnosis_excludes_transport_only_rows() -> None:
    source = Path("backend/transcribe.py").read_text()
    diagnosis = source[source.index("async def transcription_queue_diagnosis"):source.index("async def mark_missing_source_media")]
    assert "COALESCE(transport_only, 0) = 0" in diagnosis


def test_large_upload_uses_transport_chunks_without_logical_split() -> None:
    source = Path("backend/sync.py").read_text()
    assert "AsyncIterablePayload" in source
    assert "read_source_chunks" in source
    merger = Path("backend/segment_merger.py").read_text()
    assert "_split_and_register(filepath" not in merger[merger.index("async def maybe_merge_before_upload"):]


def test_legacy_chunk_recovery_is_a_dry_run_audit() -> None:
    from logical_recording_recovery import audit_legacy_chunks, transport_order

    rows = [
        {"id": 2, "filename": "capture_chunk001.mp4", "transcribed": 0, "synced": 0, "segment_index": 99},
        {"id": 1, "filename": "capture_chunk000.mp4", "transcribed": 2, "synced": 1, "segment_index": 1},
        {"id": 3, "filename": "capture_chunk002.mp4", "transcribed": 0, "synced": 0, "segment_index": 0},
    ]
    report = audit_legacy_chunks(rows)
    assert report["candidate_count"] == 3
    assert report["groups"][0]["chunk_count"] == 3
    assert report["groups"][0]["chunks"][0]["chunk_index"] == 0
    assert transport_order([{"id": 2, "transport_chunk_index": 1}, {"id": 1, "transport_chunk_index": 0}])[0]["id"] == 1


def test_large_recordings_remain_single_logical_transcription_tasks() -> None:
    source = Path("backend/segment_merger.py").read_text()
    upload_block = source[source.index("async def maybe_merge_before_upload"):]
    assert "Keeping large logical recording intact for upload" in upload_block
    assert "_split_and_register(filepath" not in upload_block


def test_queue_accepts_legacy_finished_rows_without_duration_status() -> None:
    source = Path("backend/transcribe.py").read_text()
    poll_block = source[source.index("async def poll_transcriptions"):]
    assert "duration_status = 'accepted' OR duration_status IS NULL" in poll_block
    assert "UPDATE recordings SET duration_status='accepted'" in poll_block


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
        "duration_seconds": 60.0,
        "duration_status": "accepted",
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
            duration_seconds=28.0,
            duration_status="accepted",
        )

        response = await backend_main.get_transcribe_queue()

        assert [job["recording_id"] for job in response["jobs"]] == [102]
        assert response["jobs"][0]["status"] == "待上传"
    finally:
        source_path.unlink(missing_ok=True)
        Path(db_path).unlink(missing_ok=True)


async def test_transcribe_queue_excludes_short_and_unavailable_recordings(backend_main) -> None:
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(db_path)
    try:
        await _create_queue_test_db(backend_main, db_path)
        await _insert_recording(
            db_path,
            id=105,
            filename="short_recording.mp4",
            duration_seconds=27.99,
            duration_status="too_short",
            skip_reason="时长不足",
        )
        await _insert_recording(
            db_path,
            id=106,
            filename="unavailable_recording.mp4",
            duration_seconds=None,
            duration_status="duration_unavailable",
            skip_reason="时长不可用",
        )

        response = await backend_main.get_transcribe_queue()

        assert response["jobs"] == []
        assert response["total"] == response["session_done"]
    finally:
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


async def test_stale_job_recovery_resets_only_matching_recording(backend_main) -> None:
    import transcribe

    assert transcribe._is_stale_job(
        {"job_id": "old", "created_at": "2000-01-01 00:00:00"}, now=2_000_000_000
    )
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(db_path)
    try:
        await _create_queue_test_db(backend_main, db_path)
        await _insert_recording(db_path, id=104, transcribed=1, synced=1, gpu_job_id="old")
        transcribe.aio_connect = lambda: dbmod.aio_connect(db_path)
        transcribe.GPU_SERVICE_URL = "http://gpu.invalid"

        class _Response:
            status = 200
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return None
            async def json(self): return {"recovered": True}

        class _Session:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return None
            def post(self, *args, **kwargs): return _Response()

        original_session = transcribe.aiohttp.ClientSession
        transcribe.aiohttp.ClientSession = _Session
        try:
            assert await transcribe._recover_stale_job({"id": 104, "gpu_job_id": "old"})
        finally:
            transcribe.aiohttp.ClientSession = original_session
        async with aiosqlite.connect(db_path) as con:
            row = await (await con.execute("SELECT transcribed, synced, gpu_job_id FROM recordings WHERE id=104")).fetchone()
        assert row == (0, 0, None)
    finally:
        Path(db_path).unlink(missing_ok=True)


async def test_missing_finished_source_is_marked_terminal(backend_main) -> None:
    import transcribe
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(db_path)
    try:
        await _create_queue_test_db(backend_main, db_path)
        await _insert_recording(db_path, id=107, filename="not-mounted.mp4")
        transcribe.aio_connect = lambda: dbmod.aio_connect(db_path)
        await transcribe.mark_missing_source_media(107, "not-mounted.mp4")
        async with aiosqlite.connect(db_path) as con:
            row = await (await con.execute(
                "SELECT transcribed, transcribe_error, skip_reason FROM recordings WHERE id=107"
            )).fetchone()
        assert row == (-1, "source media unavailable: not-mounted.mp4", "source media unavailable: not-mounted.mp4")
    finally:
        Path(db_path).unlink(missing_ok=True)


async def test_queue_diagnosis_classifies_pending_reasons_without_mutation(backend_main) -> None:
    import transcribe

    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(db_path)
    source_path = Path(backend_main.RECORDINGS_DIR) / "diagnosis_ready.mp4"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(b"placeholder")
    try:
        await _create_queue_test_db(backend_main, db_path)
        await _insert_recording(db_path, id=201, filename=source_path.name)
        await _insert_recording(
            db_path, id=202, filename="short.mp4", duration_status="too_short"
        )
        await _insert_recording(
            db_path, id=203, filename="open.mp4", end_time=None
        )
        await _insert_recording(
            db_path, id=204, filename="gone.mp4", transcribed=-1,
            transcribe_error="source media unavailable: recording file is missing"
        )
        await _insert_recording(
            db_path, id=205, filename="gone.srt.mp4", transcribed=-1,
            transcribe_error="source media/SRT unavailable: non-empty SRT sidecar is missing"
        )
        await _insert_recording(
            db_path, id=206, filename="running.mp4", transcribed=1,
            synced=1, gpu_job_id="gpu-job-206"
        )
        transcribe.aio_connect = lambda: dbmod.aio_connect(db_path)
        diagnosis = await transcribe.transcription_queue_diagnosis(gpu_online=False)

        assert diagnosis["counts"]["ready_to_submit"] == 0
        assert diagnosis["counts"]["duration_not_accepted"] == 1
        assert diagnosis["counts"]["end_time_invalid"] == 1
        assert diagnosis["counts"]["media_missing"] == 1
        assert diagnosis["counts"]["srt_missing"] == 1
        assert diagnosis["counts"]["gpu_job_running"] == 1
        assert diagnosis["blocked_reason"] == "gpu_offline"

        async with aiosqlite.connect(db_path) as con:
            rows = await (await con.execute(
                "SELECT id, transcribed, synced FROM recordings WHERE id IN (201, 202, 203, 204, 205, 206) ORDER BY id"
            )).fetchall()
        assert rows == [(201, 0, 0), (202, 0, 0), (203, 0, 0), (204, -1, 0), (205, -1, 0), (206, 1, 1)]
    finally:
        source_path.unlink(missing_ok=True)
        Path(db_path).unlink(missing_ok=True)


def test_transcription_watchdog_contract_is_present() -> None:
    source = Path("gpu_service/main.py").read_text()
    assert "async def _job_watchdog_loop" in source
    assert "_recover_stale_jobs()" in source
    assert "_transcription_tasks[job_id] = asyncio.create_task(_run_with_lock(job_id))" in source
    assert "_transcription_tasks.pop(job_id, None)" in source
    assert '"transcription_watchdog"' in source


def test_recovery_endpoint_cancels_worker_without_deleting_artifacts() -> None:
    source = Path("gpu_service/main.py").read_text()
    recovery_block = source[source.index("async def recover_stale_job"):source.index("async def get_srt")]
    assert "task.cancel()" in recovery_block
    assert "_db_update_job(job_id, \"error\", error)" in recovery_block
    assert "os.remove" not in recovery_block


def test_poll_health_reports_cycle_completion_and_errors() -> None:
    source = Path("backend/transcribe.py").read_text()
    status_source = Path("backend/main.py").read_text()
    assert '"last_poll_finished_at": None' in source
    assert '"poll_count": 0' in source
    assert '"last_poll_error": None' in source
    assert '_poll_state["last_poll_finished_at"] = time.time()' in source
    assert '"last_poll_finished_at": _iso(ps["last_poll_finished_at"])' in status_source
    assert '"last_poll_error": ps["last_poll_error"]' in status_source


def test_recovered_worker_cannot_publish_or_reuse_stale_upload_alias() -> None:
    source = Path("gpu_service/main.py").read_text()
    assert "temporary_srt_path = f\"{srt_path}.{job_id}.{id(job)}.tmp\"" in source
    assert "_jobs.get(job_id) is not job" in source
    assert "_remove_idempotency_aliases(job_id, job)" in source
    assert "_transcription_tasks.pop(job_id, None)" in source


async def main_test() -> None:
    backend_main = _load_backend_main()
    await test_transcribe_queue_excludes_ghost_open_recording(backend_main)
    await test_transcribe_queue_includes_finished_unsynced_recording_with_file(backend_main)
    await test_transcribe_queue_excludes_short_and_unavailable_recordings(backend_main)
    await test_stale_open_cleanup_keeps_recent_active_recording(backend_main)
    await test_stale_job_recovery_resets_only_matching_recording(backend_main)
    test_transcription_watchdog_contract_is_present()
    test_recovery_endpoint_cancels_worker_without_deleting_artifacts()
    test_poll_health_reports_cycle_completion_and_errors()
    test_recovered_worker_cannot_publish_or_reuse_stale_upload_alias()
    print("transcribe queue ghost-recording guards ok")


if __name__ == "__main__":
    asyncio.run(main_test())
