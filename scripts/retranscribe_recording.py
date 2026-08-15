#!/usr/bin/env python3
"""Explicitly retranscribe one recording on the remote GPU worker.

This tool is deliberately opt-in and does not enqueue director, creative, or
other pipelines.  Use ``--reclip`` only after reviewing the new SRT; the
existing conservative clip endpoint is then invoked for that recording alone.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sqlite3
import time
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get("DOUYIN_DB_PATH", ROOT / "backend" / "douyin.db"))
RECORDINGS_DIR = ROOT / "recordings"
GPU_SERVICE_URL = os.environ.get("GPU_SERVICE_URL", "http://10.190.0.203:8877").rstrip("/")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recording-id", type=int, required=True)
    parser.add_argument("--reclip", action="store_true", help="enqueue this recording's current clip engine after SRT download")
    parser.add_argument("--diff", action="store_true", help="print a compact old/new SRT text diff")
    return parser.parse_args()


def load_recording(recording_id: int) -> tuple[str, int]:
    with sqlite3.connect(DB_PATH) as connection:
        row = connection.execute(
            "SELECT filename, room_id FROM recordings WHERE id = ?", (recording_id,)
        ).fetchone()
    if not row:
        raise SystemExit(f"recording {recording_id} not found")
    filename, room_id = row
    if not filename or Path(filename).name != filename or "\x00" in filename:
        raise SystemExit("recording has an unsafe filename")
    if room_id is None or room_id < 1:
        raise SystemExit("recording has an invalid room id")
    return filename, room_id


async def upload_and_fetch(filename: str, room_id: int, output_path: Path) -> tuple[bytes, str]:
    source_path = RECORDINGS_DIR / filename
    if not source_path.is_file():
        raise SystemExit(f"source media not found: {source_path.name}")
    headers = {}
    token = os.environ.get("GPU_API_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    timeout = aiohttp.ClientTimeout(total=900)
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        form = aiohttp.FormData()
        form.add_field("room_id", str(room_id))
        with source_path.open("rb") as source:
            form.add_field("file", source, filename=source_path.name, content_type="video/mp4")
            headers["X-Idempotency-Key"] = f"retranscribe:{room_id}:{filename}:{time.time_ns()}"
            async with session.post(f"{GPU_SERVICE_URL}/jobs", data=form, headers=headers) as response:
                if response.status != 201:
                    raise SystemExit(f"GPU upload failed with status {response.status}")
                job_id = (await response.json()).get("job_id")
        if not job_id:
            raise SystemExit("GPU upload returned no job id")
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            async with session.get(f"{GPU_SERVICE_URL}/jobs/{job_id}") as response:
                status = await response.json() if response.status == 200 else {}
            if status.get("status") == "error":
                raise SystemExit("GPU transcription failed")
            if status.get("status") == "done":
                async with session.get(f"{GPU_SERVICE_URL}/jobs/{job_id}/srt") as response:
                    if response.status != 200:
                        raise SystemExit("GPU job completed but SRT was unavailable")
                    content = await response.read()
                output_path.write_bytes(content)
                return content, job_id
            await asyncio.sleep(5)
    raise SystemExit("timed out waiting for GPU transcription")


def mark_recording_transcribed(recording_id: int, job_id: str, reclip: bool) -> None:
    """Persist the completed remote job without touching group pipelines."""
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            """UPDATE recordings
               SET transcribed = 2, synced = 1, gpu_job_id = ?,
                   transcribe_error = NULL, clipped = CASE WHEN ? THEN 0 ELSE clipped END
               WHERE id = ?""",
            (job_id, int(reclip), recording_id),
        )
        if connection.total_changes != 1:
            raise SystemExit(f"recording {recording_id} disappeared while saving transcription")
        connection.commit()


async def main() -> None:
    args = parse_args()
    filename, room_id = load_recording(args.recording_id)
    source_path = RECORDINGS_DIR / filename
    output_path = source_path.with_suffix(".srt")
    old_path = output_path.with_suffix(output_path.suffix + ".before-asr")
    if output_path.exists():
        shutil.copy2(output_path, old_path)
    _, job_id = await upload_and_fetch(filename, room_id, output_path)
    mark_recording_transcribed(args.recording_id, job_id, args.reclip)
    print(f"wrote improved SRT: {output_path.name}")
    if args.diff and old_path.exists():
        import difflib
        old = old_path.read_text(encoding="utf-8").splitlines()
        new = output_path.read_text(encoding="utf-8").splitlines()
        print("\n".join(difflib.unified_diff(old, new, fromfile="old", tofile="new")))
    if args.reclip:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.post(f"http://127.0.0.1:8899/api/recordings/{args.recording_id}/reclip", json={}) as response:
                if response.status >= 300:
                    raise SystemExit(f"conservative reclip request failed with status {response.status}")
        print("reclip enqueued for this recording only")


if __name__ == "__main__":
    asyncio.run(main())
