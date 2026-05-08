#!/usr/bin/env python3
"""
批量检查 director_status=2 的分组，找出视频时长 < 30s 的，
将其 director_status 设为 -2，director_error 设为历史数据清理说明。
"""
import os
import subprocess
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "douyin.db")
RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), "recordings")


def probe_duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except (ValueError, AttributeError):
        return 0.0


def main():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    cur.execute(
        "SELECT id, director_final_video FROM clip_groups WHERE director_status = 2 AND director_final_video IS NOT NULL"
    )
    rows = cur.fetchall()
    print(f"Checking {len(rows)} director_status=2 groups...")

    short_groups = []
    for row in rows:
        gid = row["id"]
        video_path = row["director_final_video"]
        # director_final_video stores path relative to recordings dir or absolute
        if not os.path.isabs(video_path):
            full_path = os.path.join(RECORDINGS_DIR, video_path)
        else:
            full_path = video_path

        if not os.path.exists(full_path):
            print(f"  Group {gid}: file missing ({video_path})")
            continue

        dur = probe_duration(full_path)
        if dur < 30.0:
            print(f"  Group {gid}: {dur:.1f}s < 30s  [{os.path.basename(video_path)}]")
            short_groups.append((gid, dur, full_path))
        else:
            print(f"  Group {gid}: {dur:.1f}s OK")

    if not short_groups:
        print("\nNo short videos found.")
        con.close()
        return

    print(f"\nFound {len(short_groups)} short director videos. Updating DB...")
    for gid, dur, full_path in short_groups:
        cur.execute(
            "UPDATE clip_groups SET director_status = -2, director_error = ? WHERE id = ?",
            (f"导演版视频时长不足30s（历史数据清理）: {dur:.1f}s", gid),
        )
        print(f"  Marked group {gid} as director_status=-2")

    con.commit()
    con.close()
    print("Done.")


if __name__ == "__main__":
    main()
