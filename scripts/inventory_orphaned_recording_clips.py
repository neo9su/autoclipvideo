"""Read-only inventory and provenance checks for recording clip references.

The command opens SQLite databases in read-only mode, enables query-only mode,
and never runs migrations or writes data.  Supplying multiple database paths
allows production exports, backups, and replicas to be compared without
assuming that any one copy is authoritative.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

DEFAULT_CLIP_RANGE = (4675, 4694)
FIVE_VERSION_STATUS_COLUMNS = (
    "classic_status",
    "director_status",
    "creative_status",
    "realistic_status",
    "conservative_status",
)


def read_only_connection(database_path: str) -> sqlite3.Connection:
    path = Path(database_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"database not found: {database_path}")
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def parse_range(value: str) -> tuple[int, int]:
    parts = value.split("-", 1)
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("range must be START-END")
    try:
        start, end = (int(part) for part in parts)
    except ValueError as error:
        raise argparse.ArgumentTypeError("range bounds must be integers") from error
    if start < 1 or end < start:
        raise argparse.ArgumentTypeError("range must contain positive IDs in order")
    return start, end


def table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {str(row["name"]) for row in rows}


def table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    if table_name not in {"recording_clips", "recordings", "clip_groups"}:
        raise ValueError(f"unsupported table: {table_name}")
    return {str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table_name})")}


def schema_fingerprint(connection: sqlite3.Connection) -> str:
    rows = connection.execute(
        """SELECT name, sql FROM sqlite_master
           WHERE type IN ('table', 'index')
             AND name IN ('recording_clips', 'recordings', 'clip_groups')
           ORDER BY type, name"""
    ).fetchall()
    payload = "\n".join(f"{row['name']}:{row['sql'] or ''}" for row in rows)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _available_columns(connection: sqlite3.Connection, table: str, requested: tuple[str, ...]) -> list[str]:
    available = table_columns(connection, table)
    return [column for column in requested if column in available]


def inventory_database(
    database_path: str,
    clip_range: tuple[int, int],
    authoritative: bool = False,
) -> dict[str, Any]:
    connection = read_only_connection(database_path)
    try:
        names = table_names(connection)
        required = {"recording_clips", "recordings", "clip_groups"}
        missing_tables = sorted(required - names)
        report: dict[str, Any] = {
            "database": str(Path(database_path).expanduser().resolve()),
            "authoritative_candidate": authoritative,
            "schema_fingerprint": schema_fingerprint(connection),
            "missing_tables": missing_tables,
            "clip_id_range": list(clip_range),
            "clips": [],
        }
        if missing_tables or "id" not in table_columns(connection, "recording_clips"):
            report["error"] = "required schema is incomplete"
            return report

        clip_columns = _available_columns(
            connection,
            "recording_clips",
            ("id", "recording_id", "variant_idx", "clip_filename", "thumbnail", "created_at", "gpu_clip_job_id"),
        )
        recording_columns = _available_columns(
            connection,
            "recordings",
            ("id", "room_id", "group_id", "filename", "start_time", "end_time", "synced", "transcribed", "clipped", "local_deleted", "duration_status"),
        )
        group_columns = _available_columns(
            connection,
            "clip_groups",
            ("id", "room_id", "label", "merge_status", *FIVE_VERSION_STATUS_COLUMNS,
             "qianchuan_status", "merged_filename", "director_final_video", "creative_final_video",
             "realistic_final_video", "conservative_final_video"),
        )
        start, end = clip_range
        placeholders = ",".join("?" for _ in range(end - start + 1))
        clip_rows = connection.execute(
            f"SELECT {', '.join(clip_columns)} FROM recording_clips "
            f"WHERE id IN ({placeholders}) ORDER BY id",
            tuple(range(start, end + 1)),
        ).fetchall()
        for clip_row in clip_rows:
            clip = dict(clip_row)
            recording = None
            group = None
            recording_id = clip.get("recording_id")
            if recording_id is not None and "id" in table_columns(connection, "recordings"):
                row = connection.execute(
                    f"SELECT {', '.join(recording_columns)} FROM recordings WHERE id = ?",
                    (recording_id,),
                ).fetchone()
                recording = dict(row) if row else None
            group_id = recording.get("group_id") if recording else None
            if group_id is not None and "id" in table_columns(connection, "clip_groups"):
                row = connection.execute(
                    f"SELECT {', '.join(group_columns)} FROM clip_groups WHERE id = ?",
                    (group_id,),
                ).fetchone()
                group = dict(row) if row else None
            report["clips"].append({
                "clip": clip,
                "recording": recording,
                "group": group,
                "orphaned_recording": recording is None,
                "orphaned_group": recording is not None and group_id is not None and group is None,
            })
        report.update({
            "found_clip_count": len(report["clips"]),
            "requested_clip_count": end - start + 1,
            "referenced_recording_ids": sorted({item["clip"].get("recording_id") for item in report["clips"] if item["clip"].get("recording_id") is not None}),
            "orphaned_clip_ids": [item["clip"]["id"] for item in report["clips"] if item["orphaned_recording"]],
            "orphaned_group_clip_ids": [item["clip"]["id"] for item in report["clips"] if item["orphaned_group"]],
        })
        return report
    finally:
        connection.close()


def compare_inventories(reports: list[dict[str, Any]]) -> dict[str, Any]:
    if len(reports) < 2:
        return {"classification": "single_database_only", "detail": "compare with an authoritative export or backup before attributing cause"}
    orphan_sets = {tuple(report.get("orphaned_clip_ids", [])) for report in reports}
    if len(orphan_sets) == 1 and next(iter(orphan_sets)):
        return {"classification": "consistent_across_supplied_databases", "detail": "likely shared source/history issue; verify production lineage and backups"}
    if any(report.get("orphaned_clip_ids") for report in reports):
        return {"classification": "differs_across_supplied_databases", "detail": "likely stale/partial copy, replication/path divergence, or restore/migration discrepancy"}
    return {"classification": "no_orphan_in_supplied_databases", "detail": "monitor finding is not reproduced by supplied copies"}


def build_report(database_paths: list[str], clip_range: tuple[int, int]) -> dict[str, Any]:
    reports = [inventory_database(path, clip_range, authoritative=index == 0) for index, path in enumerate(database_paths)]
    return {
        "read_only": True,
        "mutation_performed": False,
        "qianchuan_interrupted": False,
        "clip_id_range": list(clip_range),
        "version_status_columns": list(FIVE_VERSION_STATUS_COLUMNS),
        "comparison": compare_inventories(reports),
        "databases": reports,
        "safeguards": [
            "SQLite connections use mode=ro and PRAGMA query_only=ON",
            "No migrations, UPDATE/INSERT/DELETE, service calls, retries, or deletes are performed",
            "No repair is inferred from a single database; compare authoritative lineage before any change",
        ],
    }


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", action="append", required=True, help="SQLite database path; repeat to compare copies")
    parser.add_argument("--clips", type=parse_range, default=DEFAULT_CLIP_RANGE, help="inclusive clip ID range, default 4675-4694")
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    print(json.dumps(build_report(arguments.db, arguments.clips), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
