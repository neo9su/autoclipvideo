#!/usr/bin/env python3
"""Resumable, auditable remote-GPU recording batch workflow.

The scanner is read-only.  The runner never writes below ``source_dir`` and
uses a SQLite checkpoint plus a process lease so an interrupted run can resume
without re-uploading completed inputs.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import http.client
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

DEFAULT_RETRIES = 3
RETRYABLE_HTTP = {408, 425, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class MediaPair:
    source: Path
    srt: Path
    source_size: int
    srt_size: int
    source_sha256: str
    srt_sha256: str


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def find_sidecar(source: Path) -> Path | None:
    candidates = (Path(f"{source}.srt"), source.with_suffix(".srt"))
    return next((item for item in candidates if item.is_file() and item.stat().st_size > 0), None)


def scan_pairs(source_dir: Path) -> Iterator[MediaPair]:
    """Yield valid MP4/SRT pairs without changing any source file."""
    for source in sorted(source_dir.rglob("*.mp4")):
        if not source.is_file() or source.stat().st_size <= 0:
            continue
        sidecar = find_sidecar(source)
        if sidecar is None:
            continue
        yield MediaPair(source, sidecar, source.stat().st_size, sidecar.stat().st_size,
                        sha256_file(source), sha256_file(sidecar))


def stable_job_key(pair: MediaPair) -> str:
    # Include the canonical paths as well as content fingerprints. Two
    # different recordings can legitimately have identical bytes; collapsing
    # them would silently skip one of the inputs.
    material = (
        f"{pair.source.resolve()}:{pair.srt.resolve()}:"
        f"{pair.source_sha256}:{pair.srt_sha256}:{pair.source_size}:{pair.srt_size}"
    )
    return hashlib.sha256(material.encode()).hexdigest()


def create_manifest(source_dir: Path, manifest_path: Path) -> int:
    """Create a JSONL manifest atomically; existing source files are untouched."""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    count = 0
    with temporary.open("w", encoding="utf-8") as stream:
        for pair in scan_pairs(source_dir):
            count += 1
            stream.write(json.dumps({
                "job_key": stable_job_key(pair), "source": str(pair.source.resolve()),
                "srt": str(pair.srt.resolve()), "source_size": pair.source_size,
                "srt_size": pair.srt_size, "source_sha256": pair.source_sha256,
                "srt_sha256": pair.srt_sha256, "status": "pending", "attempts": 0,
            }, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, manifest_path)
    return count


def validate_output_root(source_dir: Path, output_dir: Path) -> None:
    """Reject output locations that could overwrite or contain the sources."""
    source = source_dir.resolve()
    output = output_dir.resolve()
    if output == source or source in output.parents:
        raise ValueError("output directory must be isolated from source directory")


def validate_control_paths(source_dir: Path, *paths: Path) -> None:
    """Keep every mutable control-plane artifact outside immutable media.

    This also prevents a manifest or checkpoint created by mistake below the
    input tree from being mistaken for a recording on the next scan.
    """
    source = source_dir.resolve()
    for path in paths:
        resolved = path.resolve()
        if resolved == source or source in resolved.parents:
            raise ValueError("manifest, checkpoint, and output must be outside source directory")


def validate_manifest_item(source_dir: Path, item: dict[str, Any]) -> None:
    """Reject hand-edited manifests that escape the declared Mac input root."""
    root = source_dir.resolve()
    for field in ("source", "srt"):
        path = Path(item[field]).resolve()
        if path == root or root not in path.parents:
            raise ValueError(f"manifest_{field}_outside_source_dir")


class Checkpoint:
    """Durable job state and append-only evidence in SQLite."""
    def __init__(self, path: Path) -> None:
        self.db = sqlite3.connect(path, timeout=30)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS jobs (
            job_key TEXT PRIMARY KEY, source TEXT NOT NULL, srt TEXT NOT NULL,
            source_sha256 TEXT NOT NULL, source_size INTEGER NOT NULL,
            srt_sha256 TEXT NOT NULL, srt_size INTEGER NOT NULL,
            status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
            remote_job_id TEXT, output_mp4 TEXT, output_srt TEXT,
            failure_class TEXT, failure_reason TEXT, updated_at REAL NOT NULL,
            evidence_json TEXT NOT NULL DEFAULT '{}')""")
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(jobs)")}
        for name, definition in (("srt_sha256", "TEXT NOT NULL DEFAULT ''"),
                                 ("srt_size", "INTEGER NOT NULL DEFAULT 0")):
            if name not in columns:
                self.db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")
        self.db.commit()

    def seed(self, records: Iterator[dict[str, Any]]) -> None:
        now = time.time()
        self.db.executemany("""INSERT OR IGNORE INTO jobs
            (job_key,source,srt,source_sha256,source_size,srt_sha256,srt_size,status,updated_at)
            VALUES (?,?,?,?,?,?,?,'pending',?)""",
            ((r["job_key"], r["source"], r["srt"], r["source_sha256"], r["source_size"],
              r.get("srt_sha256", ""), r.get("srt_size", 0), now) for r in records))
        self.db.commit()

    def next_job(self, retries: int = DEFAULT_RETRIES) -> dict[str, Any] | None:
        row = self.db.execute("SELECT * FROM jobs WHERE status IN ('pending','retry') AND attempts < ? ORDER BY updated_at LIMIT 1", (retries,)).fetchone()
        if row is None:
            return None
        columns = [item[1] for item in self.db.execute("PRAGMA table_info(jobs)")]
        return dict(zip(columns, row))

    def update(self, key: str, **fields: Any) -> None:
        fields["updated_at"] = time.time()
        assignments = ",".join(f"{name}=?" for name in fields)
        self.db.execute(f"UPDATE jobs SET {assignments} WHERE job_key=?", (*fields.values(), key))
        self.db.commit()

    def counts(self) -> dict[str, int]:
        return {row[0]: row[1] for row in self.db.execute("SELECT status,COUNT(*) FROM jobs GROUP BY status")}

    def close(self) -> None:
        self.db.close()


@contextlib.contextmanager
def lease(path: Path) -> Iterator[None]:
    """Acquire an exclusive lease; stale leases require explicit operator removal."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("x", encoding="utf-8")
    try:
        handle.write(json.dumps({"pid": os.getpid(), "created_at": time.time()}))
        handle.flush()
        yield
    finally:
        handle.close()
        path.unlink(missing_ok=True)


def classify_failure(exc: Exception) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return "remote_transient" if exc.code in RETRYABLE_HTTP else "remote_permanent"
    if isinstance(exc, (TimeoutError, urllib.error.URLError)):
        return "transport"
    if isinstance(exc, (FileNotFoundError, PermissionError, ValueError)):
        return "input"
    return "unknown"


def multipart_upload(url: str, source: Path, room_id: int, idempotency_key: str,
                     timeout: float, headers: dict[str, str] | None = None) -> dict[str, Any]:
    """Upload with bounded memory; the source is never read all at once."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("gpu_url_must_be_http")
    boundary = uuid.uuid4().hex
    prefix = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"room_id\"\r\n\r\n{room_id}\r\n"
              f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{source.name}\"\r\n"
              "Content-Type: video/mp4\r\n\r\n").encode()
    suffix = f"\r\n--{boundary}--\r\n".encode()
    connection_class = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    connection = connection_class(parsed.hostname, parsed.port, timeout=timeout)
    try:
        connection.putrequest("POST", parsed.path or "/")
        connection.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
        connection.putheader("Content-Length", str(len(prefix) + source.stat().st_size + len(suffix)))
        connection.putheader("X-Idempotency-Key", idempotency_key)
        for name, value in (headers or {}).items():
            connection.putheader(name, value)
        connection.endheaders()
        connection.send(prefix)
        with source.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                connection.send(chunk)
        connection.send(suffix)
        response = connection.getresponse()
        payload = response.read()
        if response.status >= 400:
            raise urllib.error.HTTPError(url, response.status, response.reason, response.headers, None)
        return json.loads(payload)
    finally:
        connection.close()


def get_json(url: str, timeout: float, headers: dict[str, str] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def download(url: str, destination: Path, timeout: float, headers: dict[str, str] | None = None) -> dict[str, Any]:
    temporary = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=timeout) as response, temporary.open("wb") as stream:
        shutil.copyfileobj(response, stream)
    os.replace(temporary, destination)
    return {"status": response.status, "headers": {"content-length": response.headers.get("Content-Length")}}


def ffprobe(path: Path) -> dict[str, Any]:
    command = ["ffprobe", "-v", "error", "-show_entries", "format=duration,size", "-of", "json", str(path)]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise ValueError(f"ffprobe_exit_{completed.returncode}")
    return json.loads(completed.stdout).get("format", {})


def run_one(job: dict[str, Any], checkpoint: Checkpoint, args: argparse.Namespace) -> None:
    key = job["job_key"]
    source = Path(job["source"])
    output_dir = args.output_dir / key
    output_dir.mkdir(parents=True, exist_ok=True)
    attempts = job["attempts"] + 1
    checkpoint.update(key, status="processing", attempts=attempts)
    started = time.time()
    try:
        validate_manifest_item(args.source_dir, job)
        sidecar = Path(job["srt"])
        if (source.stat().st_size != job["source_size"]
                or sha256_file(source) != job["source_sha256"]):
            raise ValueError("source_changed_since_manifest")
        if (sidecar.stat().st_size != job["srt_size"]
                or sha256_file(sidecar) != job["srt_sha256"]):
            raise ValueError("srt_changed_since_manifest")
        response = multipart_upload(f"{args.gpu_url.rstrip('/')}/jobs", source, args.room_id, key, args.timeout, args.headers)
        remote_id = response.get("job_id")
        if not remote_id:
            raise ValueError("missing_remote_job_id")
        checkpoint.update(key, remote_job_id=remote_id)
        deadline = time.monotonic() + args.job_timeout
        while True:
            if args.pause_file.exists():
                raise RuntimeError("paused_by_operator")
            status = get_json(f"{args.gpu_url.rstrip('/')}/jobs/{remote_id}", args.timeout, args.headers)
            if status.get("status") == "done":
                break
            if status.get("status") in {"error", "failed"}:
                raise RuntimeError(status.get("error") or "remote_job_failed")
            if time.monotonic() > deadline:
                raise TimeoutError("remote_job_timeout")
            time.sleep(args.poll_interval)
        # A copied source is not a reclip result.  The remote adapter must
        # expose the generated MP4; fail closed when it does not.
        destination_mp4 = output_dir / source.name
        destination_srt = output_dir / f"{source.stem}.srt"
        mp4_response = download(f"{args.gpu_url.rstrip('/')}/jobs/{remote_id}/mp4", destination_mp4, args.timeout, args.headers)
        srt_response = download(f"{args.gpu_url.rstrip('/')}/jobs/{remote_id}/srt", destination_srt, args.timeout, args.headers)
        output_probe = ffprobe(destination_mp4)
        evidence = {
            "job_id": remote_id,
            "request": {"method": "POST", "path": "/jobs", "idempotency_key": key},
            "response": response,
            "mp4_response": mp4_response,
            "srt_response": srt_response,
            "gpu_consumed": True,
            "exit_code": 0,
            "output_mp4": str(destination_mp4),
            "output_srt": str(destination_srt),
            "mp4_readable": destination_mp4.is_file() and destination_mp4.stat().st_size > 0,
            "srt_readable": destination_srt.is_file() and destination_srt.stat().st_size > 0,
            "mp4_size_bytes": destination_mp4.stat().st_size,
            "srt_size_bytes": destination_srt.stat().st_size,
            "source_size": source.stat().st_size,
            "ffprobe": output_probe,
            "output_srt_sha256": sha256_file(destination_srt),
            "elapsed_s": round(time.time() - started, 3),
        }
        checkpoint.update(key, status="success", output_mp4=str(destination_mp4), output_srt=str(destination_srt), evidence_json=json.dumps(evidence, ensure_ascii=False))
    except Exception as exc:
        category = classify_failure(exc)
        status = "retry" if str(exc) == "paused_by_operator" or (attempts < args.retries and category in {"remote_transient", "transport", "unknown"}) else "permanent_failure"
        checkpoint.update(key, status=status, failure_class=category, failure_reason=str(exc)[:500], evidence_json=json.dumps({"job_id": job.get("remote_job_id"), "elapsed_s": round(time.time() - started, 3)}))


def load_manifest(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--gpu-url", required=True)
    parser.add_argument("--auth-token", default="", help="Bearer token for the private GPU API")
    parser.add_argument("--room-id", type=int, default=0)
    parser.add_argument("--sample", type=int, default=0, help="process at most N manifest entries")
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES)
    parser.add_argument("--rate-limit", type=float, default=1.0, help="seconds between uploads")
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--job-timeout", type=float, default=3600.0)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--pause-file", type=Path, default=Path("reclip.pause"))
    parser.add_argument("--scan", action="store_true", help="create manifest and exit")
    args = parser.parse_args(argv)
    if not args.source_dir.is_dir() or args.retries < 1 or args.rate_limit < 0:
        parser.error("source directory, retry limit, and rate limit are invalid")
    try:
        validate_output_root(args.source_dir, args.output_dir)
        validate_control_paths(args.source_dir, args.manifest, args.checkpoint, args.output_dir)
    except ValueError as exc:
        parser.error(str(exc))
    args.headers = {"Authorization": f"Bearer {args.auth_token}"} if args.auth_token else {}
    if args.scan:
        print(json.dumps({"candidates": create_manifest(args.source_dir, args.manifest), "manifest": str(args.manifest)}))
        return 0
    if not args.manifest.is_file():
        parser.error("manifest does not exist; run with --scan first")
    checkpoint = Checkpoint(args.checkpoint)
    checkpoint.seed(load_manifest(args.manifest))
    processed = 0
    try:
        with lease(args.checkpoint.with_suffix(args.checkpoint.suffix + ".lease")):
            while processed < args.sample if args.sample else True:
                job = checkpoint.next_job(args.retries)
                if job is None or args.pause_file.exists():
                    break
                run_one(job, checkpoint, args)
                processed += 1
                time.sleep(args.rate_limit)
    except FileExistsError:
        print("another batch runner holds the lease", file=sys.stderr)
        return 75
    finally:
        counts = checkpoint.counts()
        checkpoint.close()
    print(json.dumps({"processed": processed, "counts": counts}, ensure_ascii=False))
    return 0 if counts.get("permanent_failure", 0) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
