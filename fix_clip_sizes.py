#!/usr/bin/env python3
"""
Fix clip_size for all clips by scanning GPU service clips directory.
Maps clip_filename → md5 hash → file size.
"""

import hashlib
import json
import os
import sys
import sqlite3
from pathlib import Path

# Config
CLIPS_DIR = r"C:\Users\neo\douyin_recordings\clips"
DB_PATH = r"C:\Users\neo\douyin_backend\douyin.db"

def md5_hash(s):
    """Compute md5 hash and return first 12 chars."""
    return hashlib.md5(s.encode('utf-8')).hexdigest()[:12]

def scan_gpu_clips():
    """Scan GPU service clips directory and build {hash: size} mapping."""
    print("Scanning GPU service clips directory...")
    
    hash_to_size = {}
    clips_path = Path(CLIPS_DIR)
    
    if not clips_path.exists():
        print(f"Error: Clips directory not found: {CLIPS_DIR}")
        return {}
    
    for f in clips_path.rglob("clip.mp4"):
        if f.is_file():
            h = f.parent.name
            hash_to_size[h] = f.stat().st_size
    
    total_size = sum(hash_to_size.values())
    print(f"Found {len(hash_to_size)} clip directories, total size: {total_size/1024/1024:.2f} MB")
    return hash_to_size

def fix_clip_sizes():
    """Fix clip_size in database."""
    print("Connecting to database...")
    
    if not os.path.exists(DB_PATH):
        print(f"Error: Database not found at {DB_PATH}")
        sys.exit(1)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Scan GPU clips
    hash_to_size = scan_gpu_clips()
    if not hash_to_size:
        print("Error: Could not scan GPU clips")
        sys.exit(1)
    
    # Get all clips
    cursor.execute("SELECT id, clip_filename, clip_size FROM recording_clips")
    clips = cursor.fetchall()
    print(f"Found {len(clips)} clips to check")
    
    updated = 0
    skipped = 0
    not_found = 0
    
    for clip_id, clip_filename, current_size in clips:
        if current_size is not None:
            skipped += 1
            continue
        
        # Compute hash from clip_filename
        h = md5_hash(clip_filename)
        
        if h in hash_to_size:
            size = hash_to_size[h]
            cursor.execute("UPDATE recording_clips SET clip_size = ? WHERE id = ?", (size, clip_id))
            updated += 1
            if updated % 100 == 0:
                print(f"Updated {updated} clips...")
        else:
            not_found += 1
    
    conn.commit()
    conn.close()
    
    print(f"\nDone! Updated: {updated}, Skipped (already has size): {skipped}, Not found in clips dir: {not_found}")
    return updated

if __name__ == "__main__":
    fix_clip_sizes()
