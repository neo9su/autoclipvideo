#!/usr/bin/env python3
"""
SRT Recovery - batch processor.
Processes recordings missing SRT files by submitting jobs to the GPU service.
Designed to be run periodically (e.g., via cron or manual trigger).
"""

import asyncio
import os
import sys
import sqlite3
import aiohttp
import time

GPU_SERVICE_URL = os.environ.get("GPU_SERVICE_URL", "http://10.190.0.203:8877")
DB_PATH = os.path.join(os.path.dirname(__file__), "douyin.db")
RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), "recordings")
BATCH_SIZE = int(os.environ.get("SRT_BATCH_SIZE", "5"))
TIMEOUT = aiohttp.ClientTimeout(total=60)


def get_needing_srt(limit=100):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cur = conn.execute("""
        SELECT id, filename, room_id FROM recordings
        WHERE local_deleted = 0 AND filename IS NOT NULL
          AND transcribed IN (0, 2)
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    conn.close()

    missing = []
    for r in rows:
        fp = os.path.join(RECORDINGS_DIR, r[1])
        sp = fp + ".srt"
        if os.path.exists(fp) and not os.path.exists(sp):
            missing.append(r)
    return missing


async def submit_job(session, filepath, room_id, filename):
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


async def poll_and_save(session, job_id, output_path, recording_id):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    tries = 0
    max_tries = 60  # 5 min max
    while tries < max_tries:
        tries += 1
        try:
            async with session.get(f"{GPU_SERVICE_URL}/jobs/{job_id}",
                                    timeout=TIMEOUT) as resp:
                if resp.status == 200:
                    body = await resp.json()
                    if body.get("status") == "done":
                        async with session.get(f"{GPU_SERVICE_URL}/jobs/{job_id}/srt",
                                                timeout=TIMEOUT) as srt_resp:
                            if srt_resp.status == 200:
                                content = await srt_resp.read()
                                with open(output_path, "wb") as f:
                                    f.write(content)
                                conn.execute(
                                    "UPDATE recordings SET transcribed=2, synced=0 WHERE id=?",
                                    (recording_id,))
                                conn.commit()
                                conn.close()
                                return True, f"Saved {len(content)} bytes"
                        break
                    elif body.get("status") == "failed":
                        conn.close()
                        return False, body.get("error", "job failed")
        except Exception:
            pass
        await asyncio.sleep(5)
    conn.close()
    return False, "timeout"


async def main():
    print(f"=== SRT Recovery (batch={BATCH_SIZE}) ===")
    print(f"GPU: {GPU_SERVICE_URL}")

    missing = get_needing_srt(limit=BATCH_SIZE * 3)
    print(f"Found {len(missing)} recordings needing SRT")

    if not missing:
        print("Nothing to do.")
        return

    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        # Check GPU health
        try:
            async with session.get(f"{GPU_SERVICE_URL}/health", timeout=TIMEOUT) as resp:
                if resp.status == 200:
                    health = await resp.json()
                    print(f"GPU: ok, busy={health.get('gpu_busy')}, queue={health.get('queue_depth')}")
                else:
                    print(f"GPU health check failed: {resp.status}")
        except Exception as e:
            print(f"Cannot reach GPU service: {e}")
            return

        tasks = []
        for rec in missing[:BATCH_SIZE]:
            rec_id, filename, room_id = rec
            filepath = os.path.join(RECORDINGS_DIR, filename)
            srt_path = filepath + ".srt"

            job_id, err = await submit_job(session, filepath, room_id, filename)
            if err:
                print(f"  FAIL {filename}: {err}")
                continue

            print(f"  SUBMITTED {filename} -> {job_id}")
            tasks.append(poll_and_save(session, job_id, srt_path, rec_id))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, r in enumerate(results):
                if isinstance(r, Exception):
                    print(f"  ERROR {missing[i][1]}: {r}")
                elif r[0]:
                    print(f"  DONE {missing[i][1]}: {r[1]}")
                else:
                    print(f"  TIMEOUT {missing[i][1]}")

    # Final count
    remaining = get_needing_srt(limit=1000)
    print(f"\nRemaining needing SRT: {len(remaining)}")


if __name__ == "__main__":
    asyncio.run(main())
