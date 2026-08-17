"""Dry-run inventory of verified recordings shorter than 28 seconds.

This command never deletes files or changes the database.
"""
import argparse
import json
import sqlite3
import subprocess
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from duration_policy import MIN_RECORDING_DURATION_SECONDS, classify_duration


def _probe(path: Path) -> float | None:
    try:
        completed = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=10, check=True,
        )
        return float(completed.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def build_inventory(db_path: str, recordings_dir: str) -> dict:
    root = Path(recordings_dir).resolve()
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        columns = {row[1] for row in connection.execute("PRAGMA table_info(recordings)")}
        duration_column = "duration_seconds" if "duration_seconds" in columns else "NULL AS duration_seconds"
        rows = connection.execute(
            f"SELECT id, filename, {duration_column}, size_bytes FROM recordings ORDER BY id"
        ).fetchall()

    items = []
    for row in rows:
        path = (root / row["filename"]).resolve() if row["filename"] else None
        duration = row["duration_seconds"]
        if duration is None and path and path.is_file():
            duration = _probe(path)
        if classify_duration(duration) != "too_short":
            continue
        size = path.stat().st_size if path and path.is_file() else int(row["size_bytes"] or 0)
        items.append({
            "recording_id": row["id"],
            "path": str(path) if path else None,
            "duration_seconds": duration,
            "size_bytes": size,
        })
    return {
        "threshold_seconds": MIN_RECORDING_DURATION_SECONDS,
        "dry_run": True,
        "count": len(items),
        "total_reclaimable_bytes": sum(item["size_bytes"] for item in items),
        "items": items,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="douyin.db")
    parser.add_argument("--recordings-dir", default="recordings")
    args = parser.parse_args()
    print(json.dumps(build_inventory(args.db, args.recordings_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
