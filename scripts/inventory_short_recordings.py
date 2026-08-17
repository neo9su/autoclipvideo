#!/usr/bin/env python3
"""Print a non-destructive inventory of recordings shorter than 28 seconds."""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import aiosqlite

from db import DB_PATH
from duration_policy import MIN_RECORDING_DURATION, inventory_row, probe_duration, classify_duration


async def main() -> None:
    items = []
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT id, filename, size_bytes FROM recordings ORDER BY id") as cursor:
            rows = await cursor.fetchall()
        for row in rows:
            path = os.path.join(os.path.dirname(__file__), "..", "recordings", row["filename"])
            duration = await probe_duration(path)
            status, reason = classify_duration(duration)
            if status == "too_short":
                items.append(inventory_row({**dict(row), "duration_seconds": duration, "duration_status": status, "skip_reason": reason}))
    print(json.dumps({"dry_run": True, "threshold_seconds": MIN_RECORDING_DURATION,
                      "items": items, "total_reclaimable_bytes": sum(i["size_bytes"] for i in items)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
