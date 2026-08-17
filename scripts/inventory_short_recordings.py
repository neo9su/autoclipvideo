#!/usr/bin/env python3
"""Dry-run inventory of recordings below the processing duration floor.

This command never deletes files or database rows. Probe failures are reported
as unavailable and are deliberately not candidates for deletion.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from duration_policy import MIN_RECORDING_DURATION, classify_duration  # noqa: E402


def probe_duration(path: Path) -> float | None:
    try:
        output = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
        value = float(output)
        return value if value >= 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def inventory(database: Path, recordings_root: Path) -> dict:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        "SELECT id, filename, size_bytes FROM recordings ORDER BY id"
    ).fetchall()
    items = []
    unavailable = []
    reclaimable = 0
    for row in rows:
        path = (recordings_root / row["filename"]).resolve()
        try:
            path.relative_to(recordings_root.resolve())
        except ValueError:
            unavailable.append({"recording_id": row["id"], "path": row["filename"], "reason": "invalid_path"})
            continue
        duration = probe_duration(path) if path.is_file() else None
        status = classify_duration(duration)
        if status == "too_short":
            size = path.stat().st_size
            items.append({"recording_id": row["id"], "path": str(path), "duration_seconds": duration, "size_bytes": size})
            reclaimable += size
        elif status == "unavailable":
            unavailable.append({"recording_id": row["id"], "path": str(path), "reason": "duration_unavailable"})
    connection.close()
    return {"threshold_seconds": MIN_RECORDING_DURATION, "dry_run": True, "short_recordings": items,
            "short_count": len(items), "reclaimable_bytes": reclaimable, "unavailable": unavailable}


def main() -> None:
    parser = argparse.ArgumentParser(description="Inventory, but do not delete, short recordings")
    parser.add_argument("--db", type=Path, default=Path("douyin.db"))
    parser.add_argument("--recordings-root", type=Path, default=Path("recordings"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = inventory(args.db, args.recordings_root)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
