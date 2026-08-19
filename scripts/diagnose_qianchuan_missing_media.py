#!/usr/bin/env python3
"""Read-only diagnosis for Qianchuan groups whose source media is absent.

The command never opens a writable database connection, calls a service, or
changes queue/group state. It reports the exact source rows that an operator
must make available to the backend storage mount before retrying Qianchuan.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

# Allow direct execution from the repository root without changing the service
# import contract.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from media_contract import audit_media_file  # noqa: E402

DEFAULT_GROUP_IDS = (4675, 4676, 4677, 4678, 4679, 4680, 4681, 4682, 4683, 4684, 4687)
EXPECTED_RECORDING_IDS = (20204, 20205, 20206, 20207, 20208, 20209, 20210, 20211, 20212, 20213, 20217)


def read_only_connection(database_path: str) -> sqlite3.Connection:
    database = Path(database_path).expanduser().resolve()
    if not database.is_file():
        raise FileNotFoundError(f"database not found: {database_path}")
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def diagnose_groups(database_path: str, storage_root: str, group_ids: tuple[int, ...]) -> dict[str, Any]:
    """Return media evidence for selected groups without mutating any state."""
    import media_contract

    media_contract.STORAGE_DIR = Path(storage_root).expanduser().resolve()
    connection = read_only_connection(database_path)
    try:
        group_columns = {row[1] for row in connection.execute("PRAGMA table_info(clip_groups)")}
        file_status_column = "qianchuan_file_status" if "qianchuan_file_status" in group_columns else None
        groups: list[dict[str, Any]] = []
        for group_id in group_ids:
            selected = ["id", "label", "qianchuan_status", "qianchuan_final_video"]
            if file_status_column:
                selected.append(file_status_column)
            group = connection.execute(
                f"SELECT {', '.join(selected)} FROM clip_groups WHERE id = ?", (group_id,)
            ).fetchone()
            if not group:
                groups.append({"group_id": group_id, "missing_group": True})
                continue
            recordings = connection.execute(
                """SELECT id, filename, clip_filename, synced, transcribed, clipped,
                          local_deleted, duration_status
                   FROM recordings WHERE group_id = ? ORDER BY id""",
                (group_id,),
            ).fetchall()
            media = []
            for recording in recordings:
                filename = recording["filename"]
                evidence = audit_media_file(filename) if filename else {
                    "filename": filename, "valid_filename": False,
                    "mp4": {"readable": False}, "srt": {"readable": False}, "ready": False,
                }
                media.append({"recording": dict(recording), "evidence": evidence})
            groups.append({
                "group_id": group_id,
                "label": group["label"],
                "qianchuan_status": group["qianchuan_status"],
                "qianchuan_file_status": group[file_status_column] if file_status_column else None,
                "qianchuan_final_video": group["qianchuan_final_video"],
                "recordings": media,
            })
        return {
            "read_only": True,
            "database": str(Path(database_path).expanduser().resolve()),
            "storage_root": str(Path(storage_root).expanduser().resolve()),
            "group_ids": list(group_ids),
            "expected_recording_ids": list(EXPECTED_RECORDING_IDS),
            "groups": groups,
            "operator_action": (
                "Make the listed source MP4 and readable SRT sidecars available under the backend "
                "storage mount (operator sync_mp4_to_storage prerequisite), then re-run this diagnosis. "
                "Only after every required source reports ready should the listed groups be retried."
            ),
        }
    finally:
        connection.close()


def parse_ids(value: str) -> tuple[int, ...]:
    try:
        ids = tuple(dict.fromkeys(int(item.strip()) for item in value.split(",") if item.strip()))
    except ValueError as error:
        raise argparse.ArgumentTypeError("group IDs must be comma-separated integers") from error
    if not ids:
        raise argparse.ArgumentTypeError("at least one group ID is required")
    return ids


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="SQLite database path")
    parser.add_argument("--storage-root", required=True, help="Backend media storage mount")
    parser.add_argument("--groups", type=parse_ids, default=DEFAULT_GROUP_IDS,
                        help="comma-separated group IDs; defaults to the affected groups")
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()
    print(json.dumps(diagnose_groups(args.db, args.storage_root, args.groups), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
