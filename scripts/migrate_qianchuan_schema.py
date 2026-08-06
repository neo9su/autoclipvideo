#!/usr/bin/env python3
"""Idempotently migrate a control/backend SQLite database for Qianchuan."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from qianchuan_schema import QIANCHUAN_COLUMNS, missing_qianchuan_columns

DEFAULT_DB = Path(__file__).resolve().parents[1] / "douyin.db"


def migrate_database(database_path: Path) -> list[str]:
    """Add missing Qianchuan columns and return the columns added."""
    with sqlite3.connect(database_path) as connection:
        table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'clip_groups'"
        ).fetchone()
        if not table_exists:
            raise RuntimeError(f"clip_groups table is missing from {database_path}")

        missing = missing_qianchuan_columns(connection)
        for name in missing:
            connection.execute(
                f"ALTER TABLE clip_groups ADD COLUMN {name} {QIANCHUAN_COLUMNS[name]}"
            )
        connection.commit()

        remaining = missing_qianchuan_columns(connection)
        if remaining:
            raise RuntimeError(
                "migration incomplete; missing columns: " + ", ".join(remaining)
            )
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(os.environ.get("DOUYIN_DB_PATH", DEFAULT_DB)),
        help="SQLite database used by the running backend (default: repository douyin.db)",
    )
    args = parser.parse_args()
    database_path = args.db.expanduser().resolve()
    if not database_path.exists():
        raise SystemExit(f"database does not exist: {database_path}")

    added = migrate_database(database_path)
    print(f"Qianchuan fact-source DB: {database_path}")
    print("Added columns: " + (", ".join(added) if added else "none (already current)"))
    print("Verified columns: " + ", ".join(QIANCHUAN_COLUMNS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
