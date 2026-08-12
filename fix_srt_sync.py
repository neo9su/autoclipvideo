#!/usr/bin/env python3
"""
Fix SRT file / database inconsistency.

Problem: 1692 SRT files exist on disk, but 0 match any recording in the database.
Solution: Sync database state with actual SRT files on disk.
"""

import asyncio
import os
import sys
import time

import aiohttp

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))
os.environ.setdefault("DEPLOYMENT_ROLE", "gpu-backend")

from db import aio_connect

GPU_SERVICE_URL = os.environ.get("GPU_SERVICE_URL", "http://10.190.0.203:8877")
RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), "recordings")
POLL_INTERVAL = 5
MAX_CONCURRENT = 5


async def sync_srt_status(db):
    """Scan disk for SRT files and update database to reflect reality."""
    print("Scanning SRT files on disk...")
    srt_files = {}
    for f in os.listdir(RECORDINGS_DIR):
        if f.endswith('.srt'):
            base = f[:-5]  # Remove .srt
            srt_files[base] = os.path.join(RECORDINGS_DIR, f)
    
    print(f"Found {len(srt_files)} SRT files on disk")
    
    # Get all recordings
    print("Fetching recordings from database...")
    cur = await db.execute("SELECT id, filename, transcribed FROM recordings")
    recordings = {}
    for row in await cur.fetchall():
        recordings[row[1]] = {"id": row[0], "transcribed": row[2]}
    
    print(f"Found {len(recordings)} recordings in database")
    
    # Find matches
    matched = 0
    updated = 0
    for srt_base, srt_path in srt_files.items():
        if srt_base in recordings:
            rec_id = recordings[srt_base]["id"]
            current_status = recordings[srt_base]["transcribed"]
            if current_status != 2:
                # Update database to reflect SRT exists
                await db.execute(
                    "UPDATE recordings SET transcribed = 2, synced = 1 WHERE id = ?",
                    (rec_id,)
                )
                updated += 1
                print(f"  Updated recording {rec_id}: {srt_base}")
            matched += 1
    
    await db.commit()
    print(f"\nSync complete:")
    print(f"  SRT files on disk: {len(srt_files)}")
    print(f"  Matching recordings: {matched}")
    print(f"  Database updated: {updated}")
    
    return matched, updated


async def main():
    print("=" * 60)
    print("SRT Database Sync Tool")
    print("=" * 60)
    
    start = time.time()
    
    async with aio_connect() as db:
        matched, updated = await sync_srt_status(db)
    
    elapsed = time.time() - start
    print(f"\nCompleted in {elapsed:.1f}s")
    
    if updated > 0:
        print("\nNext step: Re-run qianchuan generation for affected groups")
    else:
        print("\nNo updates needed. SRT files and database are in sync.")


if __name__ == "__main__":
    asyncio.run(main())
