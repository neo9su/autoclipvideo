#!/usr/bin/env python3
"""Resumable dual-version processing inventory and dispatcher for issue #112.

The default command only inventories state.  ``--execute`` submits missing work
through the existing API without resetting completed artifacts or fabricating DB
status.  Every decision is written to a JSONL audit log for restart/review.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

STATUS_NAMES = {2: "done", 1: "running", 0: "pending", -1: "failed", -2: "blocked", -3: "stale"}
DEFAULT_DB = Path(__file__).resolve().parent / "douyin.db"
DEFAULT_API = "http://localhost:8899"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inventory and resume director/classic processing")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--execute", action="store_true", help="submit missing work; never resets completed work")
    parser.add_argument("--poll-seconds", type=float, default=0.0)
    parser.add_argument("--limit", type=int, default=0, help="limit groups for a controlled run (0 means all)")
    parser.add_argument("--report", type=Path, default=Path("issue112_batch_report.jsonl"))
    return parser.parse_args()


def status_name(value: Any) -> str:
    try:
        return STATUS_NAMES.get(int(value), f"unknown:{value}")
    except (TypeError, ValueError):
        return "unknown"


def connect(db_path: Path) -> sqlite3.Connection:
    if not db_path.is_file():
        raise FileNotFoundError(f"database not found: {db_path}")
    connection = sqlite3.connect(str(db_path), timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def inventory(connection: sqlite3.Connection, limit: int = 0) -> list[dict[str, Any]]:
    sql = """
        SELECT g.id, g.label, g.merge_status, g.classic_status,
               g.director_status, g.merged_filename, g.director_final_video,
               g.merge_error, g.director_error, g.cover_candidates,
               COUNT(r.id) AS recordings,
               SUM(CASE WHEN r.clipped = 2 AND r.clip_filename IS NOT NULL THEN 1 ELSE 0 END) AS ready_clips,
               SUM(CASE WHEN r.clipped IN (0, 1) THEN 1 ELSE 0 END) AS active_clips,
               SUM(CASE WHEN r.clipped = -1 THEN 1 ELSE 0 END) AS failed_clips
        FROM clip_groups g
        LEFT JOIN recordings r ON r.group_id = g.id
        GROUP BY g.id
        ORDER BY g.id
    """
    rows = [dict(row) for row in connection.execute(sql)]
    return rows[:limit] if limit > 0 else rows


def classify(row: dict[str, Any]) -> dict[str, Any]:
    ready = int(row.get("ready_clips") or 0)
    classic = int(row.get("classic_status") or 0)
    director = int(row.get("director_status") or 0)
    reasons: list[str] = []
    if ready == 0:
        reasons.append("no_ready_clips")
    if classic != 2 and ready == 0:
        reasons.append("classic_waits_for_clip_pipeline")
    if director != 2 and classic != 2:
        reasons.append("director_waits_for_classic")
    return {
        "group_id": row["id"],
        "classic": status_name(classic),
        "director": status_name(director),
        "ready_clips": ready,
        "recordings": int(row.get("recordings") or 0),
        "failed_clips": int(row.get("failed_clips") or 0),
        "reasons": reasons,
    }


def post(api_base: str, path: str) -> tuple[bool, str]:
    request = urllib.request.Request(api_base.rstrip("/") + path, method="POST", data=b"", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return True, response.read().decode("utf-8", errors="replace")[:500]
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, str(exc)


def gpu_diagnostics(api_base: str) -> dict[str, Any]:
    request = urllib.request.Request(api_base.rstrip("/") + "/health", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return {"reachable": True, "health": payload}
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return {"reachable": False, "error": str(exc)}


def write_report(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def dispatch(rows: list[dict[str, Any]], api_base: str, report_path: Path, execute: bool) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    for row in rows:
        item = classify(row)
        action = "skip"
        detail = "already_complete"
        if item["ready_clips"] == 0:
            detail = "missing_or_unprocessed_clips"
        elif item["classic"] != "done":
            action = "classic"
            detail = "classic_missing_or_retryable"
        elif item["director"] != "done":
            action = "director"
            detail = "director_missing_or_retryable"
        elif not row.get("cover_candidates"):
            action = "covers"
            detail = "classic_cover_missing"
        if execute and action != "skip":
            endpoint = f"/api/groups/{row['id']}/merge" if action == "classic" else f"/api/groups/{row['id']}/retry-modes" if action == "director" else f"/api/groups/{row['id']}/generate-covers"
            ok, response = post(api_base, endpoint)
            item.update({"submitted": ok, "response": response, "endpoint": endpoint})
        else:
            item["submitted"] = False
        item.update({"action": action, "detail": detail, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
        decisions.append(item)
    write_report(report_path, decisions)
    return decisions


def print_summary(rows: list[dict[str, Any]], decisions: list[dict[str, Any]], gpu: dict[str, Any]) -> None:
    counts = Counter((item["classic"], item["director"]) for item in decisions)
    actions = Counter(item["action"] for item in decisions)
    print(f"groups={len(rows)}")
    print("version_pairs=" + json.dumps({f"{a}/{b}": count for (a, b), count in sorted(counts.items())}, ensure_ascii=False))
    print("actions=" + json.dumps(dict(sorted(actions.items())), ensure_ascii=False))
    print("gpu=" + json.dumps(gpu, ensure_ascii=False))


def main() -> int:
    args = parse_args()
    try:
        with connect(args.db) as connection:
            rows = inventory(connection, args.limit)
    except (OSError, sqlite3.Error) as exc:
        print(f"inventory_failed={exc}")
        return 2
    gpu = gpu_diagnostics(args.api)
    decisions = dispatch(rows, args.api, args.report, args.execute)
    print_summary(rows, decisions, gpu)
    if not args.execute:
        print("dry_run=true; use --execute only after reviewing the JSONL report")
    if args.poll_seconds > 0:
        time.sleep(args.poll_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
