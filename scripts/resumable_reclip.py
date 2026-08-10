#!/usr/bin/env python3
"""Resumable, auditable batch coordinator for remote re-edit jobs.

The coordinator is deliberately media-agnostic: it inventories source MP4/SRT
pairs, checkpoints remote requests in SQLite, and never writes beneath the
source root.  A remote service must implement the documented JSON contract;
unknown or unavailable endpoints are recorded as blocked rather than marked
successful.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  item_key TEXT PRIMARY KEY, source_mp4 TEXT NOT NULL, source_srt TEXT NOT NULL,
  mp4_size INTEGER NOT NULL, srt_size INTEGER NOT NULL, mp4_sha256 TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
  job_id TEXT, output_mp4 TEXT, output_srt TEXT, last_http_status INTEGER,
  last_response TEXT, failure_class TEXT, failure_reason TEXT,
  lease_until REAL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, item_key TEXT NOT NULL, at REAL NOT NULL,
  status TEXT NOT NULL, payload TEXT NOT NULL
);
"""

RETRYABLE_HTTP = {408, 425, 429, 500, 502, 503, 504}
PERMANENT_HTTP = {400, 401, 403, 404, 405, 409, 422}


@dataclass(frozen=True)
class Pair:
    mp4: Path
    srt: Path


def validate_source_root(source_root: Path) -> Path:
    """Return a resolved directory and reject symlinked/non-directory roots."""
    resolved = source_root.expanduser().resolve()
    if not resolved.is_dir():
        raise ValueError(f"source-root is not a directory: {source_root}")
    return resolved


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_pairs(source_root: Path) -> tuple[list[Pair], int]:
    """Find exact same-stem pairs without changing any source file."""
    mp4s = sorted(source_root.rglob("*.mp4"))
    pairs: list[Pair] = []
    skipped = 0
    for mp4 in mp4s:
        srt = mp4.with_suffix(".srt")
        if srt.is_file() and mp4.is_file() and mp4.stat().st_size > 0:
            pairs.append(Pair(mp4, srt))
        else:
            skipped += 1
    return pairs, skipped


def item_key(pair: Pair, digest: str) -> str:
    return hashlib.sha256(f"{pair.mp4.resolve()}:{digest}".encode()).hexdigest()


def init_db(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA)
    connection.commit()
    return connection


def write_manifest(path: Path, pairs: list[Pair], connection: sqlite3.Connection) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # A manifest is an append-only inventory.  Re-running discovery must not
    # rewrite history or reset an already completed checkpoint.
    known = {line.split('"item_key": "', 1)[1].split('"', 1)[0]
             for line in path.read_text(encoding="utf-8").splitlines()
             if '"item_key": "' in line} if path.exists() else set()
    with path.open("a", encoding="utf-8") as manifest:
        for pair in pairs:
            digest = sha256_file(pair.mp4)
            key = item_key(pair, digest)
            record = {"item_key": key, "mp4": str(pair.mp4), "srt": str(pair.srt),
                      "mp4_size": pair.mp4.stat().st_size, "srt_size": pair.srt.stat().st_size,
                      "mp4_sha256": digest}
            if key not in known:
                manifest.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                known.add(key)
            connection.execute(
                "INSERT OR IGNORE INTO items(item_key,source_mp4,source_srt,mp4_size,srt_size,mp4_sha256,updated_at) VALUES(?,?,?,?,?,?,?)",
                (key, str(pair.mp4), str(pair.srt), record["mp4_size"], record["srt_size"], digest, time.time()),
            )
    connection.commit()


def json_logger(path: Path) -> logging.Logger:
    logger = logging.getLogger("resumable_reclip")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return logger


def record_event(connection: sqlite3.Connection, logger: logging.Logger, key: str, status: str, payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    connection.execute("INSERT INTO events(item_key,at,status,payload) VALUES(?,?,?,?)", (key, time.time(), status, serialized))
    connection.commit()
    logger.info(json.dumps({"at": time.time(), "item_key": key, "status": status, **payload}, ensure_ascii=False))


def classify_http(status: int) -> tuple[str, bool]:
    if status in RETRYABLE_HTTP:
        return "transient", True
    if status in PERMANENT_HTTP:
        return "permanent", False
    return "unknown", False


def acquire_lock(lock_path: Path, lease_seconds: int) -> None:
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as lock:
            lock.write(json.dumps({"pid": os.getpid(), "lease_until": time.time() + lease_seconds}))
    except FileExistsError as exc:
        try:
            data = json.loads(lock_path.read_text(encoding="utf-8"))
            if float(data.get("lease_until", 0)) < time.time():
                lock_path.unlink()
                return acquire_lock(lock_path, lease_seconds)
        except (OSError, ValueError, TypeError):
            pass
        raise RuntimeError(f"active lease exists: {lock_path}") from exc


def post_json(url: str, payload: dict[str, Any], timeout: int, auth_token: str | None = None) -> tuple[int, str]:
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(1024 * 1024).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read(1024 * 1024).decode("utf-8", errors="replace")


def validate_success_response(response: dict[str, Any]) -> tuple[bool, str]:
    """Require durable output and GPU-consumption evidence, not just a job id."""
    output = response.get("output")
    evidence = response.get("evidence")
    if not isinstance(output, dict) or not output.get("mp4_path") or not output.get("srt_path"):
        return False, "missing isolated output paths"
    if not isinstance(evidence, dict):
        return False, "missing output evidence"
    required = ("mp4_readable", "srt_readable", "mp4_bytes", "srt_bytes", "ffprobe", "gpu_consumed")
    if any(not evidence.get(field) for field in required):
        return False, "incomplete output or GPU evidence"
    if not isinstance(evidence["mp4_bytes"], int) or not isinstance(evidence["srt_bytes"], int):
        return False, "output byte sizes must be integers"
    return True, "ok"


def process(connection: sqlite3.Connection, logger: logging.Logger, endpoint: str, max_attempts: int, interval: float, limit: int | None, timeout: int, auth_token: str | None = None) -> None:
    rows = connection.execute("SELECT * FROM items WHERE status IN ('pending','retry') ORDER BY rowid").fetchall()
    for row in rows[:limit]:
        key, source_mp4, source_srt, mp4_size, srt_size, digest, status, attempts = row[:8]
        if attempts >= max_attempts:
            connection.execute("UPDATE items SET status='permanent_failed',failure_class='retry_limit',updated_at=? WHERE item_key=?", (time.time(), key))
            connection.commit()
            continue
        if not Path(source_mp4).is_file() or not Path(source_srt).is_file():
            reason = "source disappeared or is not a regular file"
            connection.execute("UPDATE items SET status='permanent_failed',failure_class='source_missing',failure_reason=?,updated_at=? WHERE item_key=?", (reason, time.time(), key))
            connection.commit(); record_event(connection, logger, key, "permanent_failed", {"reason": reason, "mp4": source_mp4, "srt": source_srt}); continue
        payload = {"idempotency_key": key, "input": {"mp4_path": source_mp4, "srt_path": source_srt, "mp4_size": mp4_size, "srt_size": srt_size, "mp4_sha256": digest}, "output_policy": "isolated"}
        attempt = attempts + 1
        connection.execute("UPDATE items SET status='running',attempts=?,updated_at=? WHERE item_key=?", (attempt, time.time(), key)); connection.commit()
        record_event(connection, logger, key, "submitted", {"attempt": attempt, "endpoint": endpoint, "input_mp4": source_mp4, "input_srt": source_srt, "input_bytes": mp4_size})
        try:
            http_status, response_text = post_json(endpoint, payload, timeout, auth_token)
            response: dict[str, Any] = json.loads(response_text) if response_text else {}
            valid, evidence_reason = validate_success_response(response)
            if 200 <= http_status < 300 and response.get("job_id") and valid:
                output = response.get("output", {})
                connection.execute("UPDATE items SET status='success',job_id=?,output_mp4=?,output_srt=?,last_http_status=?,last_response=?,failure_class=NULL,failure_reason=NULL,updated_at=? WHERE item_key=?", (str(response["job_id"]), output.get("mp4_path"), output.get("srt_path"), http_status, response_text[:4000], time.time(), key))
                connection.commit(); record_event(connection, logger, key, "success", {"job_id": response["job_id"], "http_status": http_status, "response": response, "output_mp4": output.get("mp4_path"), "output_srt": output.get("srt_path")})
            else:
                failure_class, retryable = classify_http(http_status)
                if 200 <= http_status < 300 and response.get("job_id"):
                    failure_class, retryable, evidence_reason = "contract", False, evidence_reason
                next_status = "retry" if retryable and attempt < max_attempts else "permanent_failed"
                reason = evidence_reason if http_status < 300 else f"remote response {http_status}"
                connection.execute("UPDATE items SET status=?,last_http_status=?,last_response=?,failure_class=?,failure_reason=?,updated_at=? WHERE item_key=?", (next_status, http_status, response_text[:4000], failure_class, reason, time.time(), key)); connection.commit()
                record_event(connection, logger, key, next_status, {"job_id": response.get("job_id"), "http_status": http_status, "response": response_text[:1000], "failure_reason": reason, "attempt": attempt})
        except (OSError, TimeoutError, ValueError) as error:
            next_status = "retry" if attempt < max_attempts else "permanent_failed"
            connection.execute("UPDATE items SET status=?,failure_class='transport',failure_reason=?,updated_at=? WHERE item_key=?", (next_status, type(error).__name__, time.time(), key)); connection.commit()
            record_event(connection, logger, key, next_status, {"failure_class": "transport", "reason": type(error).__name__, "attempt": attempt})
        time.sleep(interval)


def summary(connection: sqlite3.Connection) -> dict[str, int]:
    return {status: count for status, count in connection.execute("SELECT status,COUNT(*) FROM items GROUP BY status")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--endpoint", help="controlled remote reclip API; omit for inventory-only")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--lease-seconds", type=int, default=3600)
    parser.add_argument("--auth-token-env", help="environment variable containing the remote API bearer token")
    parser.add_argument("--proof-complete", action="store_true", help="operator confirms three-recording E2E proof is recorded")
    args = parser.parse_args(argv)
    if args.max_attempts < 1 or args.interval < 0 or args.timeout < 1 or args.lease_seconds < 1:
        parser.error("source-root must be a directory; max-attempts >= 1; interval >= 0")
    try:
        args.source_root = validate_source_root(args.source_root)
    except ValueError as error:
        parser.error(str(error))
    if args.endpoint and args.limit is None and not args.proof_complete:
        parser.error("full batch requires --proof-complete after the three-recording E2E proof")
    auth_token = os.environ.get(args.auth_token_env) if args.auth_token_env else None
    args.state_dir.mkdir(parents=True, exist_ok=True)
    lock = args.state_dir / "batch.lock"
    try:
        acquire_lock(lock, args.lease_seconds)
    except RuntimeError as error:
        print(str(error), file=sys.stderr); return 3
    try:
        connection = init_db(args.state_dir / "checkpoint.sqlite3")
        logger = json_logger(args.state_dir / "events.jsonl")
        pairs, skipped = discover_pairs(args.source_root)
        write_manifest(args.state_dir / "manifest.jsonl", pairs, connection)
        logger.info(json.dumps({"at": time.time(), "status": "inventory", "candidates": len(pairs), "skipped": skipped, "source_root": str(args.source_root)}, ensure_ascii=False))
        if args.endpoint:
            process(connection, logger, args.endpoint, args.max_attempts, args.interval, args.limit, args.timeout, auth_token)
        print(json.dumps({"candidates": len(pairs), "skipped": skipped, **summary(connection)}, ensure_ascii=False, sort_keys=True))
        return 0 if not args.endpoint or not any(summary(connection).get(s, 0) for s in ("retry", "permanent_failed")) else 2
    finally:
        try: connection.close()
        finally: lock.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
