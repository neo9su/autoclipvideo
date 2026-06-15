#!/usr/bin/env python3
"""
Fix 23 groups (id 943-969) that have classic_status=2, director_status=-1, creative_status=-1
but NO recordings on disk (all files deleted/cleaned up).

These groups were from 2026-04-01. Their recordings were cleaned up during disk maintenance.
The merged videos are also missing from disk.

Two approaches:
1. If recordings still exist under different group_ids → reassign them
2. If not → reset director/creative to 0, clear merged_filename, let backfill re-merge when new recordings arrive

Strategy: Find the room_id from the original recordings, then find the latest group_id for that room_id
that has recordings, and reassign the orphan recordings to that group.
"""

import sqlite3
import os
import glob

DB_PATH = "/Users/claw/work/douyin-recorder/douyin.db"
RECORDINGS_DIR = "/Users/claw/work/douyin-recorder/recordings"

TARGET_GROUP_IDS = list(range(943, 970))  # 943-969

def main():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    c = db.cursor()
    
    # Step 1: Find original recordings for these groups
    # Since recordings are gone, check if there are ANY recordings with matching patterns
    # Actually these groups are empty, so we need a different approach
    
    # Step 2: Check if there are NEW recordings for the same room_ids
    # The rooms that were active around April 1, 2026 had room_ids 1, 2, 3
    # Check what the current room_ids are and if new recordings were added
    
    # Since these groups have NO recordings and NO files on disk,
    # the simplest fix is to:
    # 1. Reset director_status and creative_status to 0
    # 2. Clear merged_filename (so backfill doesn't think they're done)
    # 3. These groups will be re-merged naturally when/if new recordings are added
    
    target_groups = []
    c.execute('''
        SELECT id, label FROM clip_groups 
        WHERE id IN ({}) AND classic_status=2 AND merged_filename IS NOT NULL
        AND director_status=-1 AND creative_status=-1
        ORDER BY id
    '''.format(','.join(str(i) for i in TARGET_GROUP_IDS)))
    
    for r in c.fetchall():
        target_groups.append(r)
    
    print(f"Groups to fix: {len(target_groups)}")
    
    for r in target_groups:
        gid = r["id"]
        label = r["label"]
        
        # Reset director and creative
        c.execute("UPDATE clip_groups SET director_status=0, creative_status=0, merged_filename=NULL WHERE id=?", (gid,))
        print(f"  Reset group {gid}: {label[:50]}... (cleared merged_filename, director/creative=0)")
    
    db.commit()
    
    # Verify
    c.execute('''SELECT COUNT(*) FROM clip_groups 
        WHERE classic_status=2 AND merged_filename IS NULL 
        AND director_status=0 AND creative_status=0''')
    print(f"\nGroups now with classic_status=2 but no merged: {c.fetchone()[0]}")
    
    c.execute('''SELECT COUNT(*) FROM clip_groups 
        WHERE classic_status=2 AND merged_filename IS NOT NULL
        AND director_status=-1 AND creative_status=-1''')
    print(f"Still -1/-1 groups: {c.fetchone()[0]}")
    
    db.close()

if __name__ == "__main__":
    main()
