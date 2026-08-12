#!/usr/bin/env python3
"""
Re-transcribe recordings that are missing SRT files (parallel version).
"""

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))
os.environ.setdefault("DEPLOYMENT_ROLE", "gpu-backend")

import aiohttp
import aiosqlite
from db import aio_connect

GPU_SERVICE_URL = os.environ.get("GPU_SERVICE_URL", "http://10.190.0.203:8877")
RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), "recordings")
UPLOAD_TIMEOUT = aiohttp.ClientTimeout(total=300)
POLL_INTERVAL = 5
MAX_CONCURRENT = 10  # Process this many recordings in parallel


async def reset_recording(db, recording_id: int):
    """Reset recording status to trigger re-transcription."""
    await db.execute("""
        UPDATE recordings 
        SET transcribed = 0, synced = 0, gpu_job_id = NULL 
        WHERE id = ?
    """, (recording_id,))
    await db.commit()


async def upload_to_gpu(session: aiohttp.ClientSession, filepath: str, room_id: int, filename: str) -> str:
    """Upload a video to the GPU service and return the job ID."""
    url = f"{GPU_SERVICE_URL}/jobs"
    
    with open(filepath, "rb") as f:
        file_data = f.read()
    
    form = aiohttp.FormData()
    form.add_field("room_id", str(room_id))
    form.add_field("file", file_data, filename=filename, content_type="video/mp4")
    
    async with session.post(url, data=form) as resp:
        if resp.status == 201:
            body = await resp.json()
            return body.get("job_id")
        else:
            text = await resp.text()
            raise RuntimeError(f"Upload failed: {resp.status} {text[:200]}")


async def poll_for_srt(session: aiohttp.ClientSession, job_id: str, srt_path: str, timeout: int = 300) -> bool:
    """Poll until SRT is available, then save it."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            async with session.get(f"{GPU_SERVICE_URL}/jobs/{job_id}/srt", timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    content = await resp.read()
                    with open(srt_path, "wb") as f:
                        f.write(content)
                    return True
                elif resp.status == 404:
                    await asyncio.sleep(POLL_INTERVAL)
                    continue
                else:
                    await asyncio.sleep(POLL_INTERVAL)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            await asyncio.sleep(POLL_INTERVAL)
    return False


async def process_recording(rec: dict):
    """Process a single recording: reset, upload, poll for SRT."""
    rid = rec["id"]
    filename = rec["filename"]
    filepath = rec["filepath"]
    srt_path = rec["srt_path"]
    room_id = rec["room_id"]
    
    try:
        # Reset status
        async with aio_connect() as db:
            await reset_recording(db, rid)
        
        # Upload and poll
        async with aiohttp.ClientSession(timeout=UPLOAD_TIMEOUT) as session:
            job_id = await upload_to_gpu(session, filepath, room_id, filename)
            if not job_id:
                return False, "No job ID"
            
            if await poll_for_srt(session, job_id, srt_path):
                return True, f"job={job_id}"
            else:
                return False, "Timeout"
    except Exception as e:
        return False, str(e)


async def main():
    print("=== SRT Recovery Script (Parallel) ===")
    start_time = time.time()
    
    # Find recordings missing SRT
    async with aio_connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT r.id, r.filename, r.room_id
            FROM recordings r
            WHERE r.transcribed = 2
              AND r.local_deleted = 0
              AND r.gpu_job_id IS NOT NULL
              AND r.filename IS NOT NULL
        """) as cur:
            rows = await cur.fetchall()
    
    missing = []
    for row in rows:
        filepath = os.path.join(RECORDINGS_DIR, row["filename"])
        srt_path = filepath + ".srt"
        if os.path.exists(filepath) and not os.path.exists(srt_path):
            missing.append({
                "id": row["id"],
                "filename": row["filename"],
                "room_id": row["room_id"],
                "filepath": filepath,
                "srt_path": srt_path,
            })
    
    print(f"Found {len(missing)} recordings missing SRT")
    
    if not missing:
        print("Nothing to do.")
        return
    
    # Process in parallel batches
    success = 0
    failed = 0
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    
    async def process_with_semaphore(rec):
        nonlocal success, failed
        async with semaphore:
            ok, msg = await process_recording(rec)
            if ok:
                success += 1
            else:
                failed += 1
            print(f"  [{success+failed}/{len(missing)}] {rec['filename']}: {'OK' if ok else 'FAIL'} ({msg})", flush=True)
    
    print(f"\nProcessing with {MAX_CONCURRENT} concurrent workers...")
    tasks = [process_with_semaphore(rec) for rec in missing]
    await asyncio.gather(*tasks, return_exceptions=True)
    
    elapsed = time.time() - start_time
    print(f"\n=== Summary ===")
    print(f"Total: {len(missing)}")
    print(f"Success: {success}")
    print(f"Failed: {failed}")
    print(f"Elapsed: {elapsed:.1f}s ({elapsed/60:.1f} min)")
    
    # Verify final state
    async with aio_connect() as db:
        async with db.execute("""
            SELECT 
                SUM(CASE WHEN transcribed = 2 AND EXISTS (
                    SELECT 1 FROM recordings r2 
                    WHERE r2.filename = recordings.filename || '.srt'
                ) THEN 1 ELSE 0 END) as with_srt,
                SUM(CASE WHEN transcribed = 2 AND NOT EXISTS (
                    SELECT 1 FROM recordings r2 
                    WHERE r2.filename = recordings.filename || '.srt'
                ) THEN 1 ELSE 0 END) as without_srt
            FROM recordings
            WHERE transcribed = 2 AND local_deleted = 0
        """) as cur:
            row = await cur.fetchone()
        print(f"\nActive recordings with SRT: {row['with_srt']}")
        print(f"Active recordings without SRT: {row['without_srt']}")


if __name__ == "__main__":
    asyncio.run(main())
