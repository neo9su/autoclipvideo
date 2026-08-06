#!/usr/bin/env python3
"""安全、可恢复的千川批量重剪入口。

默认执行 dry-run；只有明确传入 ``--execute`` 才会调用 API。媒体处理由
API 后端转发到 remote-gpu，本脚本不会执行 ffmpeg/ffprobe，也不会创建发布任务。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

LOGGER = logging.getLogger("qianchuan_batch")
DEFAULT_BATCH_SIZE = 5
MAX_BATCH_SIZE = 20
TERMINAL_SUCCESS = 2
RETRYABLE_STATUSES = {0, -1, -2, -3, -4}


@dataclass(frozen=True)
class GroupCandidate:
    group_id: int
    label: str
    qianchuan_status: int
    source_count: int
    clip_count: int
    srt_count: int
    product_count: int
    audio_available: bool
    only_source: bool
    only_clip: bool
    missing_srt: bool
    missing_product: bool
    missing_audio: bool
    path_unavailable: bool
    estimated_assets: int
    output_path: Optional[str]

    @property
    def blockers(self) -> list[str]:
        reasons: list[str] = []
        if self.missing_srt:
            reasons.append("missing_srt")
        if self.missing_product:
            reasons.append("missing_product")
        if self.missing_audio:
            reasons.append("missing_audio")
        if self.path_unavailable:
            reasons.append("path_unavailable")
        return reasons


def resolve_db_path(explicit_path: Optional[str]) -> str:
    """Resolve the database using the existing environment contract."""
    configured = explicit_path or os.environ.get("DOUYIN_DB_PATH")
    if configured:
        return os.path.abspath(configured)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "douyin.db"))


def resolve_recordings_root(explicit_path: Optional[str], db_path: str) -> str:
    configured = explicit_path or os.environ.get("RECORDINGS_DIR")
    if configured:
        return os.path.abspath(configured)
    return os.path.abspath(os.path.join(os.path.dirname(db_path), "recordings"))


def safe_integer(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def recording_asset_paths(root: Path, filename: str) -> tuple[Path, Path]:
    source = root / filename
    return source, source.with_suffix(".srt")


def inspect_candidates(db_path: str, recordings_root: str) -> list[GroupCandidate]:
    """Inspect candidates read-only; this function never writes DB or files."""
    database = Path(db_path).resolve()
    if not database.is_file():
        raise FileNotFoundError(f"database not found: {db_path}")
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    root = Path(recordings_root)
    try:
        groups = connection.execute(
            "SELECT id, label, qianchuan_status, qianchuan_final_video FROM clip_groups ORDER BY id"
        ).fetchall()
        candidates: list[GroupCandidate] = []
        for group in groups:
            recordings = connection.execute(
                "SELECT filename, clip_filename, local_deleted FROM recordings WHERE group_id = ?",
                (group["id"],),
            ).fetchall()
            source_count = 0
            clip_count = 0
            srt_count = 0
            path_unavailable = False
            for recording in recordings:
                filename = recording["filename"] or ""
                if filename:
                    source_path, srt_path = recording_asset_paths(root, filename)
                    if not recording["local_deleted"] and source_path.is_file():
                        source_count += 1
                    else:
                        path_unavailable = True
                    if srt_path.is_file():
                        srt_count += 1
                    else:
                        path_unavailable = True
                clip_filename = recording["clip_filename"] or ""
                if clip_filename:
                    if (root / clip_filename).is_file():
                        clip_count += 1
                    else:
                        path_unavailable = True
            product_count = safe_integer(connection.execute(
                "SELECT COUNT(*) FROM products WHERE room_id = (SELECT room_id FROM clip_groups WHERE id = ?) AND enabled = 1",
                (group["id"],),
            ).fetchone()[0])
            voice_row = connection.execute(
                "SELECT voice_ref_clip_job_id FROM rooms WHERE id = (SELECT room_id FROM clip_groups WHERE id = ?)",
                (group["id"],),
            ).fetchone()
            audio_available = bool(voice_row and voice_row[0])
            candidates.append(GroupCandidate(
                group_id=safe_integer(group["id"]), label=group["label"] or "",
                qianchuan_status=safe_integer(group["qianchuan_status"]),
                source_count=source_count, clip_count=clip_count, srt_count=srt_count,
                product_count=product_count, audio_available=audio_available,
                only_source=source_count > 0 and clip_count == 0,
                only_clip=clip_count > 0 and source_count == 0,
                missing_srt=srt_count == 0, missing_product=product_count == 0,
                missing_audio=not audio_available, path_unavailable=path_unavailable,
                estimated_assets=source_count + clip_count,
                output_path=group["qianchuan_final_video"],
            ))
        return candidates
    finally:
        connection.close()


def output_exists(output_path: Optional[str]) -> bool:
    return bool(output_path and Path(output_path).is_file() and Path(output_path).suffix.lower() == ".mp4")


def summarize_candidates(candidates: Iterable[GroupCandidate]) -> dict[str, Any]:
    items = list(candidates)
    completed = [item for item in items if item.qianchuan_status == TERMINAL_SUCCESS and output_exists(item.output_path)]
    processable = [item for item in items if not item.blockers and item not in completed]
    return {
        "processable_groups": len(processable),
        "completed_outputs_skipped": len(completed),
        "only_source_files": sum(item.only_source for item in items),
        "only_clip": sum(item.only_clip for item in items),
        "missing_srt": sum(item.missing_srt for item in items),
        "missing_product": sum(item.missing_product for item in items),
        "missing_audio": sum(item.missing_audio for item in items),
        "path_unavailable": sum(item.path_unavailable for item in items),
        "estimated_assets": sum(item.estimated_assets for item in processable),
        "execution_node": "remote-gpu",
        "groups": [asdict(item) | {"blockers": item.blockers} for item in items],
    }


def open_json(url: str, timeout: float) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("API returned a non-object JSON response")
    return payload


def post_json(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    if not isinstance(body, dict):
        raise ValueError("API returned a non-object JSON response")
    return body


def ensure_audit_schema(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS qianchuan_batch_items (
        group_id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, status TEXT NOT NULL,
        reason TEXT, job_id TEXT, output_path TEXT, execution_node TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""")
    connection.execute("""CREATE TABLE IF NOT EXISTS qianchuan_batch_runs (
        run_id TEXT PRIMARY KEY, batch_size INTEGER NOT NULL, dry_run INTEGER NOT NULL,
        execution_node TEXT NOT NULL, summary_json TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""")


def prior_successes(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT COUNT(*) FROM qianchuan_batch_items WHERE status = 'completed' AND output_path IS NOT NULL"
    ).fetchone()
    return safe_integer(row[0])


def record_item(connection: sqlite3.Connection, run_id: str, group_id: int, status: str,
                reason: str, job_id: Optional[str], output_path: Optional[str]) -> None:
    connection.execute(
        """INSERT INTO qianchuan_batch_items
           (group_id, run_id, status, reason, job_id, output_path, execution_node)
           VALUES (?, ?, ?, ?, ?, ?, 'remote-gpu')
           ON CONFLICT(group_id) DO UPDATE SET run_id=excluded.run_id, status=excluded.status,
             reason=excluded.reason, job_id=excluded.job_id, output_path=excluded.output_path,
             execution_node=excluded.execution_node, updated_at=datetime('now')""",
        (group_id, run_id, status, reason[:500], job_id, output_path),
    )


def execute_batch(db_path: str, candidates: list[GroupCandidate], batch_size: int,
                  api_base: str, run_id: str, poll_seconds: float, timeout: float) -> dict[str, int]:
    connection = sqlite3.connect(db_path, timeout=30)
    ensure_audit_schema(connection)
    if batch_size > 3 and prior_successes(connection) < 1:
        connection.close()
        raise RuntimeError("batch_size above 3 requires at least one prior completed MP4 validation")
    connection.execute(
        "INSERT OR REPLACE INTO qianchuan_batch_runs(run_id,batch_size,dry_run,execution_node,summary_json) VALUES (?, ?, 0, 'remote-gpu', '{}')",
        (run_id, batch_size),
    )
    connection.commit()
    audited = {row[0]: row[1] for row in connection.execute("SELECT group_id,status FROM qianchuan_batch_items")}
    selected = [item for item in candidates if not item.blockers and item.qianchuan_status in RETRYABLE_STATUSES]
    selected = [item for item in selected if audited.get(item.group_id) != "completed"][:batch_size]
    counts = {"submitted": 0, "completed": 0, "failed": 0, "skipped": 0}
    for item in selected:
        try:
            response = post_json(f"{api_base.rstrip('/')}/api/v2/qianchuan/generate", {
                "group_id": item.group_id, "generate_video": True, "dry_run": False,
                "execution_node": "remote-gpu",
            }, timeout)
            if not response.get("success"):
                raise RuntimeError(response.get("error") or "pipeline rejected request")
            counts["submitted"] += 1
            deadline = time.monotonic() + timeout
            result: dict[str, Any] = {}
            while time.monotonic() < deadline:
                result = open_json(f"{api_base.rstrip('/')}/api/v2/qianchuan/group/{item.group_id}/result", timeout)
                if safe_integer(result.get("status")) != 1:
                    break
                time.sleep(poll_seconds)
            status = safe_integer(result.get("status"))
            path = result.get("final_video")
            job_id = result.get("job_id")
            if status == TERMINAL_SUCCESS and output_exists(path):
                record_item(connection, run_id, item.group_id, "completed", "remote output exists", job_id, path)
                counts["completed"] += 1
            elif status == TERMINAL_SUCCESS:
                record_item(connection, run_id, item.group_id, "failed", "output_missing", job_id, path)
                counts["failed"] += 1
            else:
                record_item(connection, run_id, item.group_id, "failed", result.get("error") or f"pipeline_status_{status}", job_id, path)
                counts["failed"] += 1
        except (OSError, ValueError, RuntimeError, urllib.error.URLError) as error:
            LOGGER.exception("qianchuan group %s failed", item.group_id)
            record_item(connection, run_id, item.group_id, "failed", str(error), None, None)
            counts["failed"] += 1
        connection.commit()
    connection.execute("UPDATE qianchuan_batch_runs SET summary_json=? WHERE run_id=?", (json.dumps(counts), run_id))
    connection.commit()
    connection.close()
    return counts


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", help="SQLite database path; defaults to the existing DB configuration")
    parser.add_argument("--recordings-root")
    parser.add_argument("--api-base", default="http://127.0.0.1:8899")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--execute", action="store_true", help="dispatch work; without this flag only read-only dry-run runs")
    parser.add_argument("--run-id", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=1800.0)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= MAX_BATCH_SIZE:
        parser.error(f"--batch-size must be between 1 and {MAX_BATCH_SIZE}")
    if args.poll_seconds <= 0 or args.timeout <= 0:
        parser.error("--poll-seconds and --timeout must be positive")
    if args.run_id is None:
        args.run_id = uuid.uuid4().hex
    return args


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_arguments()
    db_path = resolve_db_path(args.db)
    recordings_root = resolve_recordings_root(args.recordings_root, db_path)
    candidates = inspect_candidates(db_path, recordings_root)
    report = summarize_candidates(candidates)
    report.update({"db_path_configured": bool(args.db or os.environ.get("DOUYIN_DB_PATH")), "recordings_root": recordings_root})
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not args.execute:
        return 0
    counts = execute_batch(db_path, candidates, args.batch_size, args.api_base, args.run_id, args.poll_seconds, args.timeout)
    print(json.dumps({"run_id": args.run_id, "execution_node": "remote-gpu", **counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
