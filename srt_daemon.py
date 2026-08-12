#!/usr/bin/env python3
"""
Continuous SRT recovery daemon.
Processes recordings missing SRT files by submitting jobs to the GPU service.
Runs in background, processes up to BATCH_SIZE recordings per cycle.
"""

import asyncio
import os
import sys
import time
import sqlite3
import aiohttp

GPU_SERVICE_URL = os.environ.get("GPU_SERVICE_URL", "http://10.190.0.203:8877")
DB_PATH = os.path.join(os.path.dirname(__file__), "douyin.db")
RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), "recordings")
BATCH_SIZE = 5
POLL_INTERVAL = 30  # seconds between cycles
UPLOAD_TIMEOUT = aiohttp.ClientTimeout(total=60)


def get_needing_srt(conn, limit=100):
    """Get recordings that need SRT: transcribed=0/2 with MP4 on disk, no SRT."""
    cur = conn.execute("""
        SELECT id, filename, room_id FROM recordings
        WHERE local_deleted = 0 AND filename IS NOT NULL
          AND transcribed = 0
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()

    missing = []
    for r in rows:
        fp = os.path.join(RECORDINGS_DIR, r[1])
        sp = fp + ".srt"
        if os.path.exists(fp) and not os.path.exists(sp):
            missing.append(r)
    return missing


def save_srt(job_id, output_path):
    """Download SRT from GPU service and save to disk."""
    try:
        import urllib.request
        url = f"{GPU_SERVICE_URL}/jobs/{job_id}/srt"
        with urllib.request.urlopen(url, timeout=30) as resp:
            content = resp.read()
        with open(output_path, "wb") as f:
            f.write(content)
        return True, len(content)
    except Exception as e:
        return False, str(e)


def update_recording(conn, recording_id, transcribed=2):
    """Update recording transcribed status."""
    conn.execute("UPDATE recordings SET transcribed = ?, synced = 0 WHERE id = ?",
                 (transcribed, recording_id))
    conn.commit()


async def submit_job(session, filepath, room_id, filename):
    """Submit a transcription job to the GPU service."""
    try:
        url = f"{GPU_SERVICE_URL}/jobs"
        with open(filepath, "rb") as f:
            form = aiohttp.FormData()
            form.add_field("room_id", str(room_id))
            form.add_field("file", f.read(), filename=filename, content_type="video/mp4")

        async with session.post(url, data=form) as resp:
            if resp.status == 201:
                body = await resp.json()
                return body.get("job_id"), None
            else:
                text = await resp.text()
                return None, f"HTTP {resp.status}: {text}"
    except Exception as e:
        return None, str(e)


async def poll_job(session, job_id, output_path, recording_id, conn):
    """Poll until job completes, then save SRT."""
    while True:
        try:
            async with session.get(f"{GPU_SERVICE_URL}/jobs/{job_id}", timeout=UPLOAD_TIMEOUT) as resp:
                if resp.status == 200:
                    body = await resp.json()
                    if body.get("status") == "done":
                        # Download SRT
                        ok, msg = await download_srt(session, job_id, output_path)
                        if ok:
                            update_recording(conn, recording_id, 2)
                            return True, msg
                        else:
                            return False, msg
                    elif body.get("status") == "failed":
                        return False, body.get("error", "unknown error")
                # Still processing or pending
                await asyncio.sleep(5)
        except Exception as e:
            await asyncio.sleep(5)


async def download_srt(session, job_id, output_path):
    """Download SRT file from GPU service."""
    try:
        async with session.get(f"{GPU_SERVICE_URL}/jobs/{job_id}/srt",
                                timeout=UPLOAD_TIMEOUT) as resp:
            if resp.status == 200:
                content = await resp.read()
                with open(output_path, "wb") as f:
                    f.write(content)
                return True, f"Saved {len(content)} bytes"
            else:
                return False, f"HTTP {resp.status}"
    except Exception as e:
        return False, str(e)


async def main():
    print(f"=== SRT Recovery Daemon ===")
    print(f"GPU Service: {GPU_SERVICE_URL}")
    print(f"DB: {DB_PATH}")
    print(f"Batch size: {BATCH_SIZE}, Poll interval: {POLL_INTERVAL}s")
    print()

    while True:
        try:
            conn = sqlite3.connect(DB_PATH, timeout=10)
            missing = get_needing_srt(conn, limit=BATCH_SIZE * 3)
            print(f"Found {len(missing)} recordings needing SRT")

            if not missing:
                conn.close()
                print("All caught up! Sleeping...")
                await asyncio.sleep(POLL_INTERVAL)
                continue

            # Process batch
            connected = False
            try:
                async with aiohttp.ClientSession(timeout=UPLOAD_TIMEOUT) as session:
                    connected = True
            except:
                pass

            if not connected:
                print(f"Cannot connect to {GPU_SERVICE_URL}, retrying in {POLL_INTERVAL}s...")
                conn.close()
                await asyncio.sleep(POLL_INTERVAL)
                continue

            tasks = []
            for rec in missing[:BATCH_SIZE]:
                rec_id, filename, room_id = rec
                filepath = os.path.join(RECORDINGS_DIR, filename)
                srt_path = filepath + ".srt"

                # Submit job
                job_id, err = await submit_job(session, filepath, room_id, filename)
                if err:
                    print(f"  FAIL {filename}: {err}")
                    continue

                print(f"  SUBMITTED {filename} -> job {job_id}")

                # Poll for completion
                asyncio.create_task(poll_job(session, job_id, srt_path, rec_id, conn))
                tasks.append(job_id)

            conn.close()

            if tasks:
                print(f"Processing {len(tasks)} jobs, checking back in {POLL_INTERVAL}s...")
                await asyncio.sleep(POLL_INTERVAL)
            else:
                await asyncio.sleep(10)

        except Exception as e:
            print(f"Error: {e}")
            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
