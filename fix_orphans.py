#!/usr/bin/env python3
"""
Fix orphan recordings (group_id IS NULL) and recover failed transcriptions.

Steps:
1. Assign group_id to orphan recordings
2. Reset transcribed=-1 recordings (with files on disk) for re-transcription
3. Print summary of changes
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

import aiosqlite
from db import DB_PATH, aio_connect

RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), "recordings")


async def get_or_create_group_for_orphan(db, room_id):
    """
    Find the most recent clip_group for this room_id, or create one.
    Returns group_id.
    """
    # Find most recent clip_group by room_id (ordered by id DESC)
    async with db.execute(
        "SELECT id FROM clip_groups WHERE room_id = ? ORDER BY id DESC LIMIT 1",
        (room_id,),
    ) as cur:
        row = await cur.fetchone()
    if row:
        return row["id"]

    # No group exists — create one
    async with db.execute(
        "INSERT INTO clip_groups (room_id, wig_model, wig_color, label, editing_mode) VALUES (?, NULL, NULL, '孤儿分组', 'director')",
        (room_id,),
    ) as cur:
        await db.commit()
        return cur.lastrowid


async def fix_orphans():
    async with aio_connect() as db:
        db.row_factory = aiosqlite.Row

        # ── Step 1: Count orphans by category ────────────────────────────────
        async with db.execute("""
            SELECT clipped, transcribed, COUNT(*) as cnt
            FROM recordings
            WHERE group_id IS NULL
            GROUP BY clipped, transcribed
            ORDER BY clipped, transcribed
        """) as cur:
            categories = await cur.fetchall()
        print("=== Orphan recordings by (clipped, transcribed) ===")
        total_orphans = 0
        for r in categories:
            print(f"  clipped={r['clipped']}, transcribed={r['transcribed']}: {r['cnt']}")
            total_orphans += r['cnt']
        print(f"  TOTAL: {total_orphans}")
        print()

        # ── Step 2: Assign group_id to all orphans ───────────────────────────
        print("=== Assigning group_id to orphans ===")
        # Group orphans by room_id
        async with db.execute("""
            SELECT room_id, COUNT(*) as cnt
            FROM recordings
            WHERE group_id IS NULL
            GROUP BY room_id
            ORDER BY room_id
        """) as cur:
            room_groups = await cur.fetchall()

        fix_count = 0
        for rg in room_groups:
            room_id = rg["room_id"]
            group_id = await get_or_create_group_for_orphan(db, room_id)
            async with db.execute(
                "UPDATE recordings SET group_id = ? WHERE room_id = ? AND group_id IS NULL",
                (group_id, room_id),
            ):
                pass  # executed
            await db.commit()
            fix_count += rg["cnt"]
            print(f"  Room {room_id}: assigned group {group_id} to {rg['cnt']} orphans")

        print(f"  Total assigned: {fix_count}")
        print()

        # ── Step 3: Reset transcribed=-1 recordings for re-transcription ─────
        print("=== Resetting failed transcriptions for re-upload ===")
        async with db.execute("""
            SELECT id, filename, synced, room_id
            FROM recordings
            WHERE group_id IS NOT NULL
              AND transcribed = -1
              AND synced = 0
              AND local_deleted = 0
        """) as cur:
            failed = await cur.fetchall()
        print(f"  Total transcribed=-1, synced=0: {len(failed)}")

        # Check which files exist on disk
        existing = []
        missing = []
        for rec in failed:
            filepath = os.path.join(RECORDINGS_DIR, rec["filename"])
            if os.path.exists(filepath):
                existing.append(rec)
            else:
                missing.append(rec["id"])

        print(f"  Files on disk: {len(existing)}")
        print(f"  Files missing: {len(missing)}")

        # Reset transcribed=-1 to transcribed=0, synced=0 so poll loop picks them up
        if existing:
            ids = [r["id"] for r in existing]
            placeholders = ",".join(["?"] * len(ids))
            await db.execute(
                f"UPDATE recordings SET transcribed = 0, synced = 0, gpu_job_id = NULL WHERE id IN ({placeholders})",
                ids,
            )
            await db.commit()
            print(f"  Reset {len(ids)} recordings for re-transcription")
        else:
            print("  Nothing to reset")
        print()

        # ── Step 4: Verify orphan count ──────────────────────────────────────
        async with db.execute(
            "SELECT COUNT(*) FROM recordings WHERE group_id IS NULL"
        ) as cur:
            remaining = (await cur.fetchone())[0]
        print(f"=== Remaining orphans (group_id IS NULL): {remaining} ===")

        # ── Step 5: Check auto-merge readiness ───────────────────────────────
        print("\n=== Checking groups with all active recordings clipped=2 ===")
        async with db.execute("""
            SELECT g.id, g.label, g.classic_status,
                COUNT(*) FILTER (WHERE r.local_deleted = 0) as total,
                COUNT(*) FILTER (WHERE r.local_deleted = 0 AND r.clipped != -1) as active,
                COUNT(*) FILTER (WHERE r.local_deleted = 0 AND r.clipped = 2) as done
            FROM clip_groups g
            JOIN recordings r ON r.group_id = g.id
            WHERE r.local_deleted = 0
            GROUP BY g.id
            HAVING active > 0 AND active = done AND classic_status = 0
            ORDER BY g.id DESC
            LIMIT 20
        """) as cur:
            ready_groups = await cur.fetchall()
        if ready_groups:
            for g in ready_groups:
                print(f"  Group {g['id']}: {g['label']} (active={g['active']}, done={g['done']})")
            print(f"  Total ready for auto-merge: {len(ready_groups)}")
        else:
            print("  No groups are immediately ready for auto-merge")


if __name__ == "__main__":
    asyncio.run(fix_orphans())
