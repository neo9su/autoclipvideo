"""Dry-run inventory of recordings below the processing duration floor."""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import aiosqlite

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))
from duration_policy import classify_duration
from transcribe import _get_video_duration


async def inventory(database: str, recordings_dir: str) -> dict:
    rows = []
    async with aiosqlite.connect(database) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT id, filename, size_bytes FROM recordings ORDER BY id") as cursor:
            records = await cursor.fetchall()
    for record in records:
        path = Path(record["filename"])
        if not path.is_absolute():
            path = Path(recordings_dir) / path
        duration = await _get_video_duration(str(path)) if path.is_file() else 0.0
        if classify_duration(duration).status != "too_short":
            continue
        size = record["size_bytes"] or (path.stat().st_size if path.is_file() else 0)
        rows.append({"recording_id": record["id"], "path": str(path), "duration_seconds": duration, "size_bytes": size})
    return {"dry_run": True, "threshold_seconds": 28.0, "recordings": rows, "count": len(rows), "reclaimable_bytes": sum(r["size_bytes"] for r in rows)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Inventory, but do not delete, recordings shorter than 28 seconds")
    parser.add_argument("--database", default=os.environ.get("DOUYIN_DB_PATH", "douyin.db"))
    parser.add_argument("--recordings-dir", default="recordings")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(inventory(args.database, args.recordings_dir)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
