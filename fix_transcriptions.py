#!/usr/bin/env python3
"""
Reset failed transcription recordings for re-upload to GPU service.

Resets:
- synced=1 AND transcribed=-1 (GPU job lost/failed after upload) — reset to synced=0, transcribed=0
- Already did: synced=0 AND transcribed=-1 (upload failed) — reset in previous run

This allows the poll_transcriptions loop to pick them up and re-upload.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

from db import aio_connect

async def reset_failed_transcriptions():
    async with aio_connect() as db:
        db.row_factory = "Row"

        # Count synced=1 AND transcribed=-1 (uploaded but transcription failed/lost)
        async with db.execute("""
            SELECT COUNT(*) as cnt FROM recordings
            WHERE synced = 1 AND transcribed = -1 
              AND group_id IS NOT NULL AND local_deleted = 0
        """) as cur:
            total = (await cur.fetchone())["cnt"]
        print(f"=== Resetting {total} recordings (synced=1, transcribed=-1) ===")

        # Reset to synced=0, transcribed=0 so poll loop will re-upload
        await db.execute("""
            UPDATE recordings 
            SET synced = 0, transcribed = 0, gpu_job_id = NULL
            WHERE synced = 1 AND transcribed = -1
              AND group_id IS NOT NULL AND local_deleted = 0
        """)
        await db.commit()
        print(f"  Reset {total} recordings")
        print()

        # Also reset transcribed=-1, synced=0 (from previous fix) if not already done
        async with db.execute("""
            SELECT COUNT(*) as cnt FROM recordings
            WHERE synced = 0 AND transcribed = -1
              AND group_id IS NOT NULL AND local_deleted = 0
        """) as cur:
            pending = (await cur.fetchone())["cnt"]
        print(f"=== Pending re-transcription (synced=0, transcribed=-1): {pending} ===")
        if pending > 0:
            # Reset these too
            async with db.execute("""
                UPDATE recordings 
                SET synced = 0, transcribed = 0, gpu_job_id = NULL
                WHERE synced = 0 AND transcribed = -1
                  AND group_id IS NOT NULL AND local_deleted = 0
            """) as cur:
                pass
            await db.commit()
            print(f"  Reset {pending} recordings")
        else:
            print("  Nothing to reset (already done in previous run)")
        print()

        # Final summary
        async with db.execute("""
            SELECT 
                SUM(CASE WHEN transcribed = -1 THEN 1 ELSE 0 END) as still_failed,
                SUM(CASE WHEN transcribed = 0 THEN 1 ELSE 0 END) as reset_for_upload,
                COUNT(*) as total
            FROM recordings
            WHERE group_id IS NOT NULL AND local_deleted = 0
        """) as cur:
            summary = await cur.fetchone()
        print("=== Final state ===")
        print(f"  Total recordings with group_id: {summary['total']}")
        print(f"  Still transcribed=-1: {summary['still_failed']}")
        print(f"  Reset to transcribed=0 (pending upload): {summary['reset_for_upload']}")

if __name__ == "__main__":
    asyncio.run(reset_failed_transcriptions())
