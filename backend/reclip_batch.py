"""Resumable, auditable remote-GPU reclip batch primitives.

This module treats recordings as immutable inputs and persists all orchestration
state in a local SQLite checkpoint. It never uses the legacy queue as proof of
completion: completion requires downloaded artifacts and explicit GPU evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


TERMINAL = {"succeeded", "permanent_failed", "skipped"}
RETRYABLE = {"network", "remote_5xx", "timeout", "artifact"}


@dataclass(frozen=True)
class Candidate:
    mp4_path: str
    srt_path: str
    mp4_size: int
    srt_size: int
    mp4_sha256: str
    srt_sha256: str
    key: str


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def discover_candidates(input_dir: Path) -> list[Candidate]:
    """Discover only MP4 files with a same-stem SRT; never mutate either file."""
    candidates = []
    for mp4 in sorted(input_dir.rglob("*.mp4")):
        # Recorder/transcriber versions have emitted both ``x.srt`` and
        # ``x.mp4.srt``.  Select an existing non-empty sidecar without
        # changing either source file.
        sidecars = (Path(f"{mp4}.srt"), mp4.with_suffix(".srt"))
        srt = next((candidate for candidate in sidecars
                    if candidate.is_file() and candidate.stat().st_size > 0), None)
        if srt is None or not mp4.is_file() or mp4.stat().st_size == 0:
            continue
        mp4_hash = sha256_file(mp4)
        srt_hash = sha256_file(srt)
        key_material = f"{mp4.resolve()}:{mp4.stat().st_size}:{mp4_hash}:{srt.stat().st_size}:{srt_hash}"
        key = hashlib.sha256(key_material.encode()).hexdigest()
        candidates.append(Candidate(str(mp4), str(srt), mp4.stat().st_size, srt.stat().st_size, mp4_hash, srt_hash, key))
    return candidates


class Manifest:
    """SQLite checkpoint with atomic claims, leases, attempts and evidence."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=30000")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS items (
          key TEXT PRIMARY KEY, mp4_path TEXT NOT NULL, srt_path TEXT NOT NULL,
          mp4_size INTEGER NOT NULL, srt_size INTEGER NOT NULL,
          mp4_sha256 TEXT NOT NULL, srt_sha256 TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
          lease_owner TEXT, lease_until REAL, job_id TEXT, output_mp4 TEXT,
          output_srt TEXT, evidence_json TEXT, last_error TEXT,
          updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, item_key TEXT, at REAL NOT NULL,
          event TEXT NOT NULL, detail_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
        """)
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    def import_candidates(self, candidates: Iterable[Candidate]) -> int:
        count = 0
        for item in candidates:
            self.db.execute("""INSERT INTO items
              (key,mp4_path,srt_path,mp4_size,srt_size,mp4_sha256,srt_sha256,updated_at)
              VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET
              mp4_path=excluded.mp4_path,srt_path=excluded.srt_path,
              mp4_size=excluded.mp4_size,srt_size=excluded.srt_size,
              mp4_sha256=excluded.mp4_sha256,srt_sha256=excluded.srt_sha256,
              updated_at=excluded.updated_at""",
              (item.key, item.mp4_path, item.srt_path, item.mp4_size, item.srt_size,
               item.mp4_sha256, item.srt_sha256, time.time()))
            count += 1
        self.db.commit()
        return count

    def claim(self, owner: str, lease_seconds: int, max_attempts: int) -> sqlite3.Row | None:
        now = time.time()
        self.db.execute("BEGIN IMMEDIATE")
        row = self.db.execute("""SELECT * FROM items WHERE
          (status='pending' OR (status='running' AND lease_until < ?)) AND attempts < ?
          ORDER BY rowid LIMIT 1""", (now, max_attempts)).fetchone()
        if row is None:
            self.db.commit()
            return None
        self.db.execute("""UPDATE items SET status='running', attempts=attempts+1,
          lease_owner=?,lease_until=?,updated_at=? WHERE key=?""",
          (owner, now + lease_seconds, now, row["key"]))
        self._event(row["key"], "claimed", {"owner": owner, "lease_until": now + lease_seconds})
        self.db.commit()
        return self.db.execute("SELECT * FROM items WHERE key=?", (row["key"],)).fetchone()

    def record(self, key: str, status: str, **fields: object) -> None:
        if status == "succeeded":
            raw_evidence = fields.get("evidence_json")
            if not isinstance(raw_evidence, str):
                raise ValueError("succeeded items require evidence_json")
            try:
                validate_success_evidence(json.loads(raw_evidence))
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError("evidence_json must be valid JSON") from exc
        allowed = {"job_id", "output_mp4", "output_srt", "evidence_json", "last_error", "lease_owner", "lease_until"}
        updates = {name: value for name, value in fields.items() if name in allowed}
        updates.update(status=status, updated_at=time.time())
        assignments = ",".join(f"{name}=?" for name in updates)
        self.db.execute(f"UPDATE items SET {assignments} WHERE key=?", (*updates.values(), key))
        self._event(key, status, fields)
        self.db.commit()

    def _event(self, key: str, event: str, detail: dict) -> None:
        self.db.execute("INSERT INTO events(item_key,at,event,detail_json) VALUES(?,?,?,?)",
                         (key, time.time(), event, json.dumps(detail, ensure_ascii=False, default=str)))

    def counts(self) -> dict[str, int]:
        rows = self.db.execute("SELECT status,COUNT(*) count FROM items GROUP BY status").fetchall()
        return {row["status"]: row["count"] for row in rows}


def verify_immutable(item: sqlite3.Row) -> None:
    """Fail closed if an input changed since manifest creation."""
    for path_key, size_key, hash_key in (("mp4_path", "mp4_size", "mp4_sha256"), ("srt_path", "srt_size", "srt_sha256")):
        path = Path(item[path_key])
        if not path.is_file() or path.stat().st_size != item[size_key] or sha256_file(path) != item[hash_key]:
            raise RuntimeError(f"immutable input changed or disappeared: {path}")


def classify_error(error: Exception, status_code: int | None = None) -> str:
    if status_code is not None and status_code >= 500:
        return "remote_5xx"
    if isinstance(error, TimeoutError) or "timeout" in str(error).lower():
        return "timeout"
    if isinstance(error, (ConnectionError, OSError)):
        return "network"
    if "artifact" in str(error).lower() or "ffprobe" in str(error).lower():
        return "artifact"
    return "permanent"


def validate_success_evidence(evidence: dict) -> None:
    """Require artifact and remote-consumption proof before terminal success."""
    required = {
        "job_id", "request", "response", "gpu_consumed", "exit_code",
        "output_mp4", "output_srt", "mp4_readable", "srt_readable",
        "mp4_size_bytes", "srt_size_bytes", "ffprobe",
    }
    missing = sorted(required - set(evidence))
    if missing:
        raise ValueError(f"incomplete success evidence: {', '.join(missing)}")
    if not evidence["job_id"] or not evidence["gpu_consumed"]:
        raise ValueError("success evidence must include a job ID and GPU consumption")
    if evidence["exit_code"] != 0 or not evidence["mp4_readable"] or not evidence["srt_readable"]:
        raise ValueError("outputs must be readable and have zero exit code")
    if evidence["mp4_size_bytes"] <= 0 or evidence["srt_size_bytes"] <= 0:
        raise ValueError("output sizes must be positive")
    if not evidence["ffprobe"]:
        raise ValueError("ffprobe evidence is required")


def output_path(root: Path, key: str, suffix: str) -> Path:
    return root / key[:2] / key / f"output{suffix}"


def new_owner() -> str:
    return f"reclip-{os.getpid()}-{uuid.uuid4().hex[:8]}"
