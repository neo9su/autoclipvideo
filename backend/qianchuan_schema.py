"""Schema contract for the Qianchuan pipeline."""

from __future__ import annotations

from typing import Any

QIANCHUAN_COLUMNS: dict[str, str] = {
    "qianchuan_status": "INTEGER DEFAULT 0",
    "qianchuan_script": "TEXT",
    "qianchuan_segments": "TEXT",
    "qianchuan_audio_path": "TEXT",
    "qianchuan_final_video": "TEXT",
    "qianchuan_error": "TEXT",
    "qianchuan_score": "REAL",
    "qianchuan_review": "TEXT",
    "qianchuan_preview_video": "TEXT",
    "qianchuan_preview_review": "TEXT",
    "qianchuan_job_id": "TEXT",
}


def _column_names(rows: list[Any]) -> set[str]:
    return {row[1] for row in rows}


async def ensure_qianchuan_schema(db: Any) -> None:
    """Add missing Qianchuan columns without changing existing data."""
    async with db.execute("PRAGMA table_info(clip_groups)") as cursor:
        existing = _column_names(await cursor.fetchall())

    missing = [
        (name, definition)
        for name, definition in QIANCHUAN_COLUMNS.items()
        if name not in existing
    ]
    for name, definition in missing:
        await db.execute(f"ALTER TABLE clip_groups ADD COLUMN {name} {definition}")
    if missing:
        await db.commit()

    async with db.execute("PRAGMA table_info(clip_groups)") as cursor:
        remaining = set(QIANCHUAN_COLUMNS) - _column_names(await cursor.fetchall())
    if remaining:
        raise RuntimeError(
            "Qianchuan schema migration incomplete; missing columns: "
            + ", ".join(sorted(remaining))
        )


def missing_qianchuan_columns(connection: Any) -> list[str]:
    """Return missing Qianchuan columns for a synchronous sqlite connection."""
    existing = {
        row[1] for row in connection.execute("PRAGMA table_info(clip_groups)")
    }
    return [name for name in QIANCHUAN_COLUMNS if name not in existing]
