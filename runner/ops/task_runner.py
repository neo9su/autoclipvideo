from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

SCHEMA = '''
CREATE TABLE IF NOT EXISTS issues (id INTEGER PRIMARY KEY, title TEXT NOT NULL, state TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}', updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, issue_id INTEGER NOT NULL, state TEXT NOT NULL, started_at REAL NOT NULL, finished_at REAL, error TEXT, generation INTEGER NOT NULL DEFAULT 1, session_key TEXT, retry_count INTEGER NOT NULL DEFAULT 0, error_class TEXT, protocol_version TEXT NOT NULL DEFAULT '1', nonce TEXT, lease_epoch INTEGER NOT NULL DEFAULT 1, accepted_at REAL, first_activity_at REAL, UNIQUE(issue_id, id));
CREATE TABLE IF NOT EXISTS leases (issue_id INTEGER PRIMARY KEY, owner TEXT NOT NULL, expires_at REAL NOT NULL, run_id TEXT, generation INTEGER NOT NULL DEFAULT 1, epoch INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS sessions (run_id TEXT PRIMARY KEY, generation INTEGER NOT NULL, session_key TEXT NOT NULL UNIQUE, state TEXT NOT NULL, confirmed_at REAL, last_activity_at REAL, nonce TEXT, protocol_version TEXT NOT NULL DEFAULT '1', last_sequence INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_uuid TEXT NOT NULL UNIQUE, sequence INTEGER NOT NULL, kind TEXT NOT NULL, issue_id INTEGER, run_id TEXT, generation INTEGER, payload TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL, UNIQUE(run_id, sequence));
CREATE TABLE IF NOT EXISTS artifacts (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, generation INTEGER NOT NULL, kind TEXT NOT NULL, value TEXT NOT NULL, sha256 TEXT, verified INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, UNIQUE(run_id, generation, kind, value));
CREATE TABLE IF NOT EXISTS qa_records (run_id TEXT NOT NULL, generation INTEGER NOT NULL, evidence TEXT NOT NULL, passed INTEGER NOT NULL, created_at REAL NOT NULL, PRIMARY KEY(run_id, generation));
CREATE TABLE IF NOT EXISTS deploy_records (run_id TEXT NOT NULL, generation INTEGER NOT NULL, evidence TEXT NOT NULL, verified INTEGER NOT NULL, policy TEXT NOT NULL, created_at REAL NOT NULL, PRIMARY KEY(run_id, generation));
CREATE TABLE IF NOT EXISTS outbox (id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending', created_at REAL NOT NULL, delivered_at REAL);
CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'open', payload TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS coordinator_lock (name TEXT PRIMARY KEY, owner TEXT NOT NULL, acquired_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS decompositions (parent_issue_id INTEGER PRIMARY KEY, child_issue_ids TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', completed_child_issue_ids TEXT NOT NULL DEFAULT '[]', blocked_child_issue_ids TEXT NOT NULL DEFAULT '[]', updated_at REAL NOT NULL);
'''

@dataclass
class RunnerConfig:
    db: Path = Path(os.getenv("TASK_RUNNER_DB", ".runner/runner.sqlite3"))
    worker_command: str = os.getenv("TASK_RUNNER_WORKER", "")
    concurrency: int = int(os.getenv("TASK_RUNNER_CONCURRENCY", "1"))
    hard_timeout: float = float(os.getenv("TASK_RUNNER_HARD_TIMEOUT", "3600"))
    no_progress_timeout: float = float(os.getenv("TASK_RUNNER_NO_PROGRESS_TIMEOUT", "900"))
    lease_seconds: float = float(os.getenv("TASK_RUNNER_LEASE_SECONDS", "120"))
    gh_command: str = os.getenv("TASK_RUNNER_GH", "gh")
    confirm_timeout: float = float(os.getenv("TASK_RUNNER_CONFIRM_TIMEOUT", "60"))
    bootstrap_timeout: float = float(os.getenv("TASK_RUNNER_BOOTSTRAP_TIMEOUT", "120"))
    max_retries: int = int(os.getenv("TASK_RUNNER_MAX_RETRIES", "3"))
    accepted_idle_alert_after: float = float(os.getenv("TASK_RUNNER_ACCEPTED_IDLE_ALERT_AFTER", "120"))
    accepted_idle_fence_after: float = float(os.getenv("TASK_RUNNER_ACCEPTED_IDLE_FENCE_AFTER", "180"))
    accepted_idle_retries: int = int(os.getenv("TASK_RUNNER_ACCEPTED_IDLE_RETRIES", "1"))

class TaskStore:
    def __init__(self, db: str | Path, readonly=False):
        self.db = Path(db)
        self.readonly = readonly
        if readonly:
            # Dry runs must not create the database or its parent directory.
            if self.db.exists():
                self.conn = sqlite3.connect(f"file:{self.db.resolve()}?mode=ro", uri=True, timeout=30, isolation_level=None)
            else:
                self.conn = sqlite3.connect(":memory:", timeout=30, isolation_level=None)
        else:
            self.db.parent.mkdir(parents=True, exist_ok=True)
            self.conn = sqlite3.connect(self.db, timeout=30, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        if not readonly:
            self.conn.executescript(SCHEMA)
            self._migrate_schema()
        elif not self.db.exists():
            self.conn.executescript(SCHEMA)

    def _migrate_schema(self):
        """Add durable run/session fields when upgrading an earlier runner DB."""
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(runs)")}
        for name, definition in (("generation", "INTEGER NOT NULL DEFAULT 1"), ("session_key", "TEXT"), ("retry_count", "INTEGER NOT NULL DEFAULT 0"), ("error_class", "TEXT"), ("lease_epoch", "INTEGER NOT NULL DEFAULT 1"), ("accepted_at", "REAL"), ("first_activity_at", "REAL")):
            if name not in columns:
                self.conn.execute(f"ALTER TABLE runs ADD COLUMN {name} {definition}")
        event_columns = {row[1] for row in self.conn.execute("PRAGMA table_info(events)")}
        if "generation" not in event_columns:
            self.conn.execute("ALTER TABLE events ADD COLUMN generation INTEGER")
        self.conn.execute("CREATE TABLE IF NOT EXISTS sessions (run_id TEXT PRIMARY KEY, generation INTEGER NOT NULL, session_key TEXT NOT NULL UNIQUE, state TEXT NOT NULL, confirmed_at REAL, last_activity_at REAL)")
        lease_columns = {row[1] for row in self.conn.execute("PRAGMA table_info(leases)")}
        for name, definition in (("run_id", "TEXT"), ("generation", "INTEGER NOT NULL DEFAULT 1")):
            if name not in lease_columns:
                self.conn.execute(f"ALTER TABLE leases ADD COLUMN {name} {definition}")
        for name, definition in (("epoch", "INTEGER NOT NULL DEFAULT 1"),):
            if name not in lease_columns:
                self.conn.execute(f"ALTER TABLE leases ADD COLUMN {name} {definition}")
        run_columns = {row[1] for row in self.conn.execute("PRAGMA table_info(runs)")}
        for name, definition in (("protocol_version", "TEXT NOT NULL DEFAULT '1'"), ("nonce", "TEXT")):
            if name not in run_columns:
                self.conn.execute(f"ALTER TABLE runs ADD COLUMN {name} {definition}")
        session_columns = {row[1] for row in self.conn.execute("PRAGMA table_info(sessions)")}
        for name, definition in (("nonce", "TEXT"), ("protocol_version", "TEXT NOT NULL DEFAULT '1'"), ("last_sequence", "INTEGER NOT NULL DEFAULT 0")):
            if name not in session_columns:
                self.conn.execute(f"ALTER TABLE sessions ADD COLUMN {name} {definition}")
        # Older databases have an integer-only event identity. Preserve them and
        # add the idempotency fields without rewriting historical audit data.
        event_columns = {row[1] for row in self.conn.execute("PRAGMA table_info(events)")}
        if "event_uuid" not in event_columns:
            self.conn.execute("ALTER TABLE events ADD COLUMN event_uuid TEXT")
            rows = self.conn.execute("SELECT id FROM events WHERE event_uuid IS NULL").fetchall()
            for row in rows:
                self.conn.execute("UPDATE events SET event_uuid=?, sequence=? WHERE id=?", (str(uuid.uuid4()), row[0], row[0]))
        if "sequence" not in event_columns:
            self.conn.execute("ALTER TABLE events ADD COLUMN sequence INTEGER")
            self.conn.execute("UPDATE events SET sequence=id WHERE sequence IS NULL")
        self.conn.executescript('''
            CREATE TABLE IF NOT EXISTS artifacts (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, generation INTEGER NOT NULL, kind TEXT NOT NULL, value TEXT NOT NULL, sha256 TEXT, verified INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, UNIQUE(run_id, generation, kind, value));
            CREATE TABLE IF NOT EXISTS qa_records (run_id TEXT NOT NULL, generation INTEGER NOT NULL, evidence TEXT NOT NULL, passed INTEGER NOT NULL, created_at REAL NOT NULL, PRIMARY KEY(run_id, generation));
            CREATE TABLE IF NOT EXISTS deploy_records (run_id TEXT NOT NULL, generation INTEGER NOT NULL, evidence TEXT NOT NULL, verified INTEGER NOT NULL, policy TEXT NOT NULL, created_at REAL NOT NULL, PRIMARY KEY(run_id, generation));
            CREATE TABLE IF NOT EXISTS outbox (id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending', created_at REAL NOT NULL, delivered_at REAL);
            CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'open', payload TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL, updated_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS coordinator_lock (name TEXT PRIMARY KEY, owner TEXT NOT NULL, acquired_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS decompositions (parent_issue_id INTEGER PRIMARY KEY, child_issue_ids TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', completed_child_issue_ids TEXT NOT NULL DEFAULT '[]', blocked_child_issue_ids TEXT NOT NULL DEFAULT '[]', updated_at REAL NOT NULL);
        ''')

    def close(self): self.conn.close()
    def event(self, kind, issue_id=None, run_id=None, generation=None, payload=None, event_uuid=None, sequence=None):
        event_uuid = event_uuid or str(uuid.uuid4())
        if sequence is None:
            sequence = self.conn.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM events WHERE run_id IS ?", (run_id,)).fetchone()[0]
        try:
            self.conn.execute("INSERT INTO events(event_uuid,sequence,kind,issue_id,run_id,generation,payload,created_at) VALUES(?,?,?,?,?,?,?,?)", (event_uuid, sequence, kind, issue_id, run_id, generation, json.dumps(payload or {}), time.time()))
        except sqlite3.IntegrityError:
            # Replaying the same envelope is deliberately a no-op. A run may
            # already have lifecycle events at the worker's sequence number;
            # preserve both records with the next durable audit sequence.
            if self.conn.execute("SELECT 1 FROM events WHERE event_uuid=?", (event_uuid,)).fetchone():
                return
            sequence = self.conn.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM events WHERE run_id IS ?", (run_id,)).fetchone()[0]
            self.conn.execute("INSERT INTO events(event_uuid,sequence,kind,issue_id,run_id,generation,payload,created_at) VALUES(?,?,?,?,?,?,?,?)", (event_uuid, sequence, kind, issue_id, run_id, generation, json.dumps(payload or {}), time.time()))

    def acquire_coordinator(self, owner: str) -> bool:
        now = time.time()
        try:
            self.conn.execute("INSERT INTO coordinator_lock(name,owner,acquired_at) VALUES('heartbeat',?,?)", (owner, now))
            return True
        except sqlite3.IntegrityError:
            return False

    def release_coordinator(self, owner: str) -> bool:
        return bool(self.conn.execute("DELETE FROM coordinator_lock WHERE name='heartbeat' AND owner=?", (owner,)).rowcount)

    def add_artifact(self, run_id, generation, kind, value, sha256=None, verified=False) -> bool:
        if not self.is_current(run_id, generation):
            self.event("late_event_ignored", run_id=run_id, generation=generation, payload={"kind": "artifact"})
            return False
        self.conn.execute("INSERT OR IGNORE INTO artifacts(run_id,generation,kind,value,sha256,verified,created_at) VALUES(?,?,?,?,?,?,?)", (run_id, generation, kind, value, sha256, int(verified), time.time()))
        return True

    def record_evidence(self, run_id, generation, qa=None, deploy=None) -> bool:
        if not self.is_current(run_id, generation):
            self.event("late_event_ignored", run_id=run_id, generation=generation, payload={"kind": "evidence"})
            return False
        if qa is not None:
            self.conn.execute("INSERT OR REPLACE INTO qa_records VALUES(?,?,?,?,?)", (run_id, generation, json.dumps(qa), int(bool(qa.get("passed"))), time.time()))
        if deploy is not None:
            self.conn.execute("INSERT OR REPLACE INTO deploy_records VALUES(?,?,?,?,?,?)", (run_id, generation, json.dumps(deploy), int(bool(deploy.get("verified"))), deploy.get("policy", "required"), time.time()))
        return True

    def enqueue_outbox(self, key, kind, payload) -> bool:
        return bool(self.conn.execute("INSERT OR IGNORE INTO outbox(key,kind,payload,created_at) VALUES(?,?,?,?)", (key, kind, json.dumps(payload), time.time())).rowcount)

    def ingest_progress(self, run_id: str, generation: int, sequence: int,
                        event_uuid: str, payload=None) -> bool:
        """Accept a worker heartbeat exactly once and only in its fenced session."""
        if not self.is_current(run_id, generation):
            self.event("late_event_ignored", run_id=run_id, generation=generation,
                       payload={"kind": "progress", "sequence": sequence})
            return False
        session = self.conn.execute(
            "SELECT last_sequence,state FROM sessions WHERE run_id=? AND generation=?",
            (run_id, generation),
        ).fetchone()
        if not session or session[1] not in {"bootstrapped", "active", "confirmed"} or sequence <= session[0]:
            self.event("stale_event_ignored", run_id=run_id, generation=generation,
                       payload={"kind": "progress", "sequence": sequence})
            return False
        self.conn.execute("UPDATE sessions SET state='active',last_sequence=?,last_activity_at=? WHERE run_id=? AND generation=? AND last_sequence<?", (sequence, time.time(), run_id, generation, sequence))
        self.event("progress", run_id=run_id, generation=generation, payload=payload or {}, event_uuid=event_uuid, sequence=sequence)
        return True

    def reconcile(self, worktree=None) -> dict:
        """Produce a conservative report; ambiguous records are quarantined, never closed."""
        records = []
        for row in self.conn.execute("SELECT i.id,i.state,r.id,r.state,r.generation,l.owner,s.state FROM issues i LEFT JOIN runs r ON r.issue_id=i.id AND r.started_at=(SELECT MAX(started_at) FROM runs WHERE issue_id=i.id) LEFT JOIN leases l ON l.issue_id=i.id LEFT JOIN sessions s ON s.run_id=r.id WHERE i.state NOT IN ('done','closed') ORDER BY i.id"):
            issue_id, issue_state, run_id, run_state, generation, owner, session_state = row
            problems = []
            if run_id is None:
                problems.append("missing_run")
            if issue_state in {"accepted_idle", "running"} and not owner:
                problems.append("missing_lease")
            if run_id and not session_state:
                problems.append("missing_session")
            if worktree and run_id and not Path(worktree).exists():
                problems.append("missing_worktree")
            quarantined = bool(problems)
            if quarantined:
                self.conn.execute("UPDATE issues SET state='quarantined',updated_at=? WHERE id=? AND state NOT IN ('done','closed')", (time.time(), issue_id))
                self.event("quarantined", issue_id, run_id, generation, {"reasons": problems})
            records.append({"issue_id": issue_id, "issue_state": issue_state, "run_id": run_id, "run_state": run_state, "generation": generation, "session_state": session_state, "quarantined": quarantined, "reasons": problems})
        return {"records": records, "quarantined": sum(item["quarantined"] for item in records)}

    @staticmethod
    def _payload_json(payload):
        if isinstance(payload, dict):
            return payload
        try:
            return json.loads(payload or '{}')
        except (TypeError, json.JSONDecodeError):
            return {}

    def _completion_evidence(self, issue_id: int, issue_state: str, payload) -> bool:
        """Return true only for durable completion evidence, never queue state alone."""
        details = self._payload_json(payload)
        if issue_state in {'done', 'closed'}:
            return True
        if details.get('execution_complete') or details.get('executionComplete'):
            return True
        if any(details.get(name) is True for name in ('pr_merged', 'prMerged', 'merged_pr', 'mergedPr', 'merged')):
            return True
        pull_requests = details.get('pullRequests') or details.get('pull_requests') or []
        if any((request.get('mergedAt') or request.get('merged_at') or str(request.get('state', '')).lower() == 'merged') for request in pull_requests if isinstance(request, dict)):
            return True
        run = self.conn.execute(
            "SELECT 1 FROM runs WHERE issue_id=? AND state='succeeded' ORDER BY finished_at DESC LIMIT 1",
            (issue_id,),
        ).fetchone()
        if run:
            return True
        artifact = self.conn.execute(
            "SELECT 1 FROM artifacts a JOIN runs r ON r.id=a.run_id AND r.generation=a.generation "
            "WHERE r.issue_id=? AND a.verified=1 AND lower(a.kind) IN ('pr','pull_request','merged_pr','merge') LIMIT 1",
            (issue_id,),
        ).fetchone()
        return bool(artifact)

    def _has_active_execution(self, issue_id: int) -> bool:
        """Avoid fencing a worker that won the queue race before scan evidence arrived."""
        return bool(self.conn.execute(
            "SELECT 1 FROM runs WHERE issue_id=? AND state IN ('running','accepted_idle') LIMIT 1",
            (issue_id,),
        ).fetchone())

    def reconcile_completed_issues(self, remote_issues=None) -> int:
        """Mark queued issues done only when durable merged/completion evidence exists."""
        remote_by_id = {int(item['number']): item for item in (remote_issues or []) if item.get('number') is not None}
        completed = 0
        now = time.time()
        for row in self.conn.execute("SELECT id,state,payload FROM issues WHERE state IN ('queued','retryable','to_do')").fetchall():
            issue_id, issue_state, payload = row
            remote = remote_by_id.get(issue_id, {})
            if self._has_active_execution(issue_id) or not (
                self._completion_evidence(issue_id, issue_state, payload)
                or self._completion_evidence(issue_id, remote.get('state', ''), remote)
            ):
                continue
            changed = self.conn.execute(
                "UPDATE issues SET state='done',updated_at=? WHERE id=? AND state IN ('queued','retryable','to_do')",
                (now, issue_id),
            ).rowcount
            if changed:
                completed += 1
                self.event('completion_reconciled', issue_id, payload={'reason': 'merged_or_execution_evidence'})
        return completed

    def reconcile_decompositions(self, remote_issues=None) -> dict:
        """Repair parent rollups from current state; safe to call on every heartbeat.

        The transaction and conditional updates make overlapping ticks converge to
        one result.  Completion is recomputed, so a missed child event is repaired
        without emitting duplicate lifecycle events or starting another worker.
        """
        remote_by_id = {int(item['number']): item for item in (remote_issues or []) if item.get('number') is not None}
        repaired = completed = blocked = 0
        self.conn.execute('BEGIN IMMEDIATE')
        try:
            rows = self.conn.execute('SELECT * FROM decompositions WHERE status != "done"').fetchall()
            for decomposition in rows:
                parent_id = decomposition['parent_issue_id']
                child_ids = self._payload_json(decomposition['child_issue_ids'])
                parent = self.conn.execute('SELECT state,payload FROM issues WHERE id=?', (parent_id,)).fetchone()
                if not parent:
                    continue
                completed_ids, blocked_ids = [], []
                for child_id in child_ids:
                    child = self.conn.execute('SELECT state,payload FROM issues WHERE id=?', (child_id,)).fetchone()
                    remote = remote_by_id.get(int(child_id), {})
                    child_state = child['state'] if child else remote.get('state', '')
                    child_payload = child['payload'] if child else remote
                    has_completion = self._completion_evidence(child_id, child_state, child_payload) or self._completion_evidence(child_id, remote.get('state', ''), remote)
                    if has_completion and not self._has_active_execution(child_id):
                        completed_ids.append(child_id)
                        if child and child_state not in {'done', 'closed'} and self._completion_evidence(child_id, remote.get('state', ''), remote):
                            self.conn.execute("UPDATE issues SET state='done',updated_at=? WHERE id=? AND state NOT IN ('done','closed')", (time.time(), child_id))
                    elif child_state in {'blocked', 'recovery_needed', 'quarantined'}:
                        blocked_ids.append(child_id)
                new_status = 'done' if len(completed_ids) == len(child_ids) and child_ids else 'blocked' if blocked_ids and len(completed_ids) + len(blocked_ids) == len(child_ids) else 'active'
                old_completed = self._payload_json(decomposition['completed_child_issue_ids'])
                old_blocked = self._payload_json(decomposition['blocked_child_issue_ids'])
                changed = new_status != decomposition['status'] or sorted(old_completed) != sorted(completed_ids) or sorted(old_blocked) != sorted(blocked_ids)
                if not changed:
                    continue
                now = time.time()
                self.conn.execute(
                    'UPDATE decompositions SET status=?,completed_child_issue_ids=?,blocked_child_issue_ids=?,updated_at=? WHERE parent_issue_id=? AND status=?',
                    (new_status, json.dumps(sorted(completed_ids)), json.dumps(sorted(blocked_ids)), now, parent_id, decomposition['status']),
                )
                if new_status == 'done':
                    state_changed = self.conn.execute("UPDATE issues SET state='done',updated_at=? WHERE id=? AND state NOT IN ('done','closed')", (now, parent_id)).rowcount
                    completed += 1
                    if state_changed:
                        self.event('decomposition_converged', parent_id, payload={'child_issue_ids': sorted(completed_ids)})
                elif new_status == 'blocked':
                    state_changed = self.conn.execute("UPDATE issues SET state='blocked',updated_at=? WHERE id=? AND state NOT IN ('done','closed','blocked')", (now, parent_id)).rowcount
                    blocked += 1
                    if state_changed:
                        self.event('decomposition_blocked', parent_id, payload={'child_issue_ids': sorted(blocked_ids)})
                repaired += 1
            self.conn.execute('COMMIT')
        except Exception:
            self.conn.execute('ROLLBACK')
            raise
        return {'repaired': repaired, 'completed': completed, 'blocked': blocked}

    def is_current(self, run_id: str, generation: int) -> bool:
        row = self.conn.execute("SELECT generation,state FROM runs WHERE id=?", (run_id,)).fetchone()
        return bool(row and row[0] == generation and row[1] in {"running", "accepted_idle"})

    def record_activity(self, run_id: str, generation: int, kind: str = "first_tool_activity") -> bool:
        session = self.conn.execute(
            "SELECT state FROM sessions WHERE run_id=? AND generation=?",
            (run_id, generation),
        ).fetchone()
        if not self.is_current(run_id, generation) or not session or session[0] not in {"confirmed", "bootstrapped", "active"}:
            self.event("late_event_ignored", run_id=run_id, generation=generation, payload={"kind": kind})
            return False
        self.conn.execute("UPDATE sessions SET state='active', last_activity_at=? WHERE run_id=? AND generation=?", (time.time(), run_id, generation))
        self.event(kind, run_id=run_id, generation=generation)
        return True

    def confirm_session(self, run_id: str, generation: int) -> bool:
        """Confirm only the requested session belonging to the current generation."""
        if not self.is_current(run_id, generation):
            self.event("late_event_ignored", run_id=run_id, generation=generation,
                       payload={"kind": "session_confirmed"})
            return False
        changed = self.conn.execute(
            "UPDATE sessions SET state='confirmed',confirmed_at=? "
            "WHERE run_id=? AND generation=? AND state='requested'",
            (time.time(), run_id, generation),
        ).rowcount
        if changed:
            self.event("session_confirmed", run_id=run_id, generation=generation)
        return bool(changed)

    def mark_bootstrap(self, run_id: str, generation: int) -> bool:
        """Record trusted bootstrap without allowing a stale session to advance."""
        if not self.is_current(run_id, generation):
            self.event("late_event_ignored", run_id=run_id, generation=generation,
                       payload={"kind": "bootstrap"})
            return False
        session = self.conn.execute(
            "SELECT state FROM sessions WHERE run_id=? AND generation=?",
            (run_id, generation),
        ).fetchone()
        if not session or session[0] not in {"confirmed", "bootstrapped", "active"}:
            return False
        changed = self.conn.execute(
            "UPDATE sessions SET state='bootstrapped' WHERE run_id=? AND generation=?",
            (run_id, generation),
        ).rowcount
        if changed:
            self.event("bootstrap", run_id=run_id, generation=generation)
        return bool(changed)

    def finish_run(self, run_id: str, generation: int, state: str,
                   error: str | None = None, error_class: str | None = None) -> bool:
        """Finish only the currently fenced run; late completions are audit-only."""
        if not self.is_current(run_id, generation):
            self.event("late_event_ignored", run_id=run_id, generation=generation,
                       payload={"kind": "work_finish", "state": state})
            return False
        row = self.conn.execute("SELECT issue_id FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            return False
        now = time.time()
        changed = self.conn.execute(
            "UPDATE runs SET state=?,finished_at=?,error=?,error_class=? WHERE id=? AND generation=? AND state IN ('running','accepted_idle')",
            (state, now, error, error_class, run_id, generation),
        ).rowcount
        if not changed:
            self.event("late_event_ignored", row[0], run_id, generation,
                       {"kind": "work_finish", "state": state})
            return False
        issue_state = "done" if state == "succeeded" else "retryable"
        self.conn.execute("UPDATE issues SET state=?,updated_at=? WHERE id=? AND state IN ('running','accepted_idle')",
                          (issue_state, now, row[0]))
        self.event("run_finished", row[0], run_id, generation,
                   {"state": state, "error_class": error_class})
        return True
    def upsert_issue(self, issue_id, title, state="queued", payload=None):
        now = time.time()
        existing = self.conn.execute("SELECT state FROM issues WHERE id=?", (issue_id,)).fetchone()
        if existing and existing[0] in {"done", "running", "accepted_idle"}:
            state = existing[0]
        self.conn.execute("INSERT INTO issues(id,title,state,payload,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,payload=excluded.payload,updated_at=excluded.updated_at", (issue_id,title,state,json.dumps(payload or {}),now))

    def register_decomposition(self, parent_issue_id: int, child_issue_ids) -> None:
        """Persist a decomposition definition without resetting its progress."""
        child_ids = sorted({int(child_id) for child_id in child_issue_ids})
        now = time.time()
        self.conn.execute(
            "INSERT INTO decompositions(parent_issue_id,child_issue_ids,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(parent_issue_id) DO UPDATE SET child_issue_ids=excluded.child_issue_ids,updated_at=excluded.updated_at",
            (parent_issue_id, json.dumps(child_ids), now),
        )
    def claim(self, issue_id, owner, ttl, run_id=None, generation=1):
        now=time.time(); self.conn.execute("BEGIN IMMEDIATE")
        try:
            row=self.conn.execute("SELECT owner,expires_at FROM leases WHERE issue_id=?",(issue_id,)).fetchone()
            if row and row[1] > now and row[0] != owner: self.conn.execute("ROLLBACK"); return False
            self.conn.execute("INSERT INTO leases(issue_id,owner,expires_at,run_id,generation) VALUES(?,?,?,?,?) ON CONFLICT(issue_id) DO UPDATE SET owner=excluded.owner,expires_at=excluded.expires_at,run_id=excluded.run_id,generation=excluded.generation",(issue_id,owner,now+ttl,run_id,generation)); self.conn.execute("COMMIT"); self.event("lease_acquired",issue_id,run_id,generation,{"owner":owner}); return True
        except Exception: self.conn.execute("ROLLBACK"); raise
    def release(self, issue_id, owner, run_id=None, generation=None):
        """Release only the lease owned by this run; late cleanup is a no-op."""
        query = "DELETE FROM leases WHERE issue_id=? AND owner=?"
        values = [issue_id, owner]
        if run_id is not None:
            query += " AND run_id=?"
            values.append(run_id)
        if generation is not None:
            query += " AND generation=?"
            values.append(generation)
        self.conn.execute(query, values)

    def release_fenced(self, issue_id: int, owner: str, run_id: str,
                       generation: int, lease_epoch: int) -> bool:
        """Release only the exact lease epoch; late cleanup is audit-only."""
        changed = self.conn.execute(
            "DELETE FROM leases WHERE issue_id=? AND owner=? AND run_id=? AND generation=? AND epoch=?",
            (issue_id, owner, run_id, generation, lease_epoch),
        ).rowcount
        if not changed:
            self.event("late_event_ignored", issue_id, run_id, generation,
                       {"kind": "lease_release", "lease_epoch": lease_epoch})
        return bool(changed)

    def renew(self, issue_id, owner, ttl, run_id, generation) -> bool:
        """Renew only the lease fenced to the current run generation."""
        expires_at = time.time() + ttl
        changed = self.conn.execute(
            "UPDATE leases SET expires_at=? WHERE issue_id=? AND owner=? AND run_id=? AND generation=?",
            (expires_at, issue_id, owner, run_id, generation),
        ).rowcount
        if changed:
            self.event("lease_renewed", issue_id, run_id, generation)
        return bool(changed)
    def recover(self, now=None, dry_run=False):
        now=time.time() if now is None else now; expired=self.conn.execute("SELECT issue_id,owner,run_id,generation FROM leases WHERE expires_at<=?",(now,)).fetchall(); running=self.conn.execute("SELECT id,issue_id,generation FROM runs WHERE state IN ('running','accepted_idle')").fetchall()
        if not dry_run:
            for r in expired: self.conn.execute("DELETE FROM leases WHERE issue_id=? AND owner=?",(r[0],r[1])); self.event("lease_expired",r[0],r[2],r[3])
            for r in running:
                self.conn.execute("UPDATE runs SET state='interrupted',finished_at=?,error=?,error_class=? WHERE id=? AND generation=?",(now,"runner restart recovery","gateway_restart",r[0],r[2])); self.conn.execute("UPDATE issues SET state='retryable',updated_at=? WHERE id=? AND state != 'done'",(now,r[1])); self.event("run_interrupted",r[1],r[0],r[2])
                self.event("requeued", r[1], r[0], r[2], {"reason": "gateway_restart"})
        return {"expired_leases":len(expired),"interrupted_runs":len(running),"dry_run":dry_run}

    def accepted_idle_recovery(self, now: float, alert_after: float = 120,
                               fence_after: float = 180, retry_budget: int = 1,
                               dry_run: bool = False) -> dict:
        """Bound the gateway-accepted/worker-idle lane.

        Acceptance is not readiness.  At the alert threshold this records a
        deduplicated alert; at the fence threshold the run is fenced and
        requeued once, then held for manual recovery.
        """
        alerts = fenced = requeued = held = 0
        rows = self.conn.execute(
            "SELECT r.id,r.issue_id,r.generation,r.retry_count,r.accepted_at,l.owner,l.epoch "
            "FROM runs r LEFT JOIN leases l ON l.run_id=r.id AND l.generation=r.generation "
            "WHERE r.state='accepted_idle'"
        ).fetchall()
        for row in rows:
            run_id, issue_id, generation, retries, accepted_at, owner, epoch = row
            age = now - (accepted_at or now)
            if age >= alert_after:
                key = f"accepted_idle:{run_id}:{generation}"
                if not dry_run:
                    inserted = self.conn.execute(
                        "INSERT OR IGNORE INTO alerts(key,kind,payload,created_at,updated_at) VALUES(?,?,?,?,?)",
                        (key, "accepted_idle", json.dumps({"issue_id": issue_id, "age": age}), now, now),
                    ).rowcount
                    alerts += int(inserted > 0)
                    self.event("accepted_idle_alert", issue_id, run_id, generation,
                               {"age_seconds": round(age)})
                else:
                    alerts += 1
            if age < fence_after:
                continue
            fenced += 1
            if dry_run:
                continue
            changed = self.conn.execute(
                "UPDATE runs SET state='interrupted',finished_at=?,error=?,error_class=? "
                "WHERE id=? AND generation=? AND state='accepted_idle'",
                (now, "worker readiness was not verified", "accepted_idle_timeout", run_id, generation),
            ).rowcount
            if not changed:
                continue
            self.conn.execute("DELETE FROM leases WHERE issue_id=? AND run_id=? AND generation=? AND (? IS NULL OR epoch=?)",
                              (issue_id, run_id, generation, epoch, epoch))
            can_retry = retries < retry_budget
            next_state = "retryable" if can_retry else "recovery_needed"
            self.conn.execute("UPDATE issues SET state=?,updated_at=? WHERE id=? AND state IN ('accepted_idle','running')",
                              (next_state, now, issue_id))
            self.event("accepted_idle_fenced", issue_id, run_id, generation,
                       {"retry": can_retry, "reason": "worker_readiness_timeout"})
            if can_retry:
                requeued += 1
                self.event("requeued", issue_id, run_id, generation,
                           {"reason": "accepted_idle_timeout", "automatic_retry": True})
            else:
                held += 1
                self.event("recovery_needed", issue_id, run_id, generation,
                           {"reason": "accepted_idle_retry_budget_exhausted"})
        return {"alerts": alerts, "fenced": fenced, "requeued": requeued,
                "recovery_needed": held, "dry_run": dry_run}

    def startup_preflight(self, owner: str) -> dict:
        """Fail closed unless this coordinator can own durable state."""
        diagnostics = []
        if self.readonly:
            diagnostics.append("coordinator database is read-only")
        if not self.db.parent.exists() or not os.access(self.db.parent, os.W_OK):
            diagnostics.append("coordinator state directory is not writable")
        acquired = self.acquire_coordinator(owner) if not diagnostics else False
        if not acquired:
            diagnostics.append("another coordinator owns the heartbeat lock")
        return {"ok": not diagnostics, "owner": owner, "database": str(self.db),
                "diagnostics": diagnostics}
    def status(self):
        return {"issues": [dict(x) for x in self.conn.execute("SELECT * FROM issues ORDER BY id")], "runs": [dict(x) for x in self.conn.execute("SELECT * FROM runs ORDER BY started_at DESC")], "leases": [dict(x) for x in self.conn.execute("SELECT * FROM leases")], "sessions": [dict(x) for x in self.conn.execute("SELECT * FROM sessions")], "events": self.conn.execute("SELECT count(*) FROM events").fetchone()[0]}

    def pending_issue_ids(self):
        return [row[0] for row in self.conn.execute("SELECT id FROM issues WHERE state IN ('queued','retryable') ORDER BY id")]


class GitHubAdapter:
    def __init__(self, command="gh"): self.command=command
    def scan(self):
        try:
            out=subprocess.check_output([self.command,"issue","list","--json","number,title,state,pullRequests","--state","open"], text=True)
            return json.loads(out)
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError): return []

class Runner:
    def __init__(self, config=None, store=None, adapter=None, worker: Callable | None = None):
        self.config=config or RunnerConfig(); self.store=store or TaskStore(self.config.db); self.adapter=adapter or GitHubAdapter(self.config.gh_command); self.worker=worker
        # A heartbeat process must not share an owner identity with another
        # process.  Hostname/pid alone allowed overlapping ticks to overwrite
        # each other's lease when they ran in the same process.
        self.owner = f"{os.uname().nodename}:{os.getpid()}:{uuid.uuid4()}"
    def scan(self, dry_run=False):
        issues=self.adapter.scan()
        if not dry_run:
            for i in issues:
                number = i.get("number")
                title = i.get("title", f"Issue {number}")
                if number is not None: self.store.upsert_issue(number, title, "queued", i)
            self.store.reconcile_decompositions(issues)
        return issues

    def heartbeat(self, dry_run=False):
        """Run the idempotent lifecycle repair pass used by each heartbeat tick."""
        issues = self.adapter.scan()
        if dry_run:
            return {'dry_run': True, 'issues': len(issues)}
        for issue in issues:
            number = issue.get('number')
            if number is not None:
                remote_state = issue.get('state', 'queued')
                local_state = 'queued' if str(remote_state).lower() == 'open' else remote_state
                self.store.upsert_issue(number, issue.get('title', f'Issue {number}'), local_state, issue)
        self.store.reconcile_completed_issues(issues)
        return self.store.reconcile_decompositions(issues)

    def status(self):
        """Return the persisted runner state for the CLI and API callers."""
        return self.store.status()
    def run_once(self, issue_id=None, dry_run=False):
        rows=self.store.conn.execute("SELECT id,title,payload FROM issues WHERE state IN ('queued','retryable') AND (? IS NULL OR id=?) ORDER BY id",(issue_id,issue_id)).fetchall()
        if dry_run:
            return {"dry_run": True, "candidates": [{"id": row[0], "title": row[1], "payload": json.loads(row[2])} for row in rows]}
        if not rows: return None
        issue=rows[0]; owner=self.owner; iid=issue[0]
        generation = self.store.conn.execute(
            "SELECT COALESCE(MAX(generation), 0) + 1 FROM runs WHERE issue_id=?", (iid,)
        ).fetchone()[0]
        prior_failures = self.store.conn.execute(
            "SELECT COALESCE(MAX(retry_count), 0) FROM runs WHERE issue_id=?", (iid,)
        ).fetchone()[0]
        run_id=str(uuid.uuid4()); now=time.time(); session_key=f"issue:{iid}:run:{run_id}:generation:{generation}"
        if not self.store.claim(iid, owner, self.config.lease_seconds, run_id, generation):
            return None
        lease_epoch = self.store.conn.execute("SELECT epoch FROM leases WHERE issue_id=? AND run_id=? AND generation=?", (iid, run_id, generation)).fetchone()[0]
        self.store.conn.execute("INSERT INTO runs(id,issue_id,state,started_at,generation,session_key,retry_count,lease_epoch,accepted_at) VALUES(?,?,?,?,?,?,?,?,?)",(run_id,iid,"running",now,generation,session_key,prior_failures,lease_epoch,now)); self.store.conn.execute("INSERT INTO sessions(run_id,generation,session_key,state) VALUES(?,?,?,?)",(run_id,generation,session_key,"requested")); self.store.event("session_requested",iid,run_id,generation)
        self.store.conn.execute("UPDATE runs SET state='accepted_idle',accepted_at=? WHERE id=? AND generation=?",(now,run_id,generation)); self.store.conn.execute("UPDATE issues SET state='accepted_idle',updated_at=? WHERE id=?",(now,iid))
        try:
            if not self.store.confirm_session(run_id, generation):
                raise TimeoutError("session confirmation timeout")
            if not self.store.mark_bootstrap(run_id, generation):
                raise TimeoutError("bootstrap timeout")
            self.store.record_activity(run_id, generation)
            self.store.conn.execute("UPDATE runs SET first_activity_at=? WHERE id=? AND generation=? AND first_activity_at IS NULL", (time.time(), run_id, generation))
            if self.worker: result=self.worker(dict(issue))
            elif self.config.worker_command: result=self._execute(self.config.worker_command, iid)
            else: result=0
            succeeded = result is None or result is True or (isinstance(result, int) and not isinstance(result, bool) and result == 0)
            state="succeeded" if succeeded else "failed"; err=None if state=="succeeded" else str(result); error_class=None if state=="succeeded" else "worker_failed"
        except TimeoutError as exc: state,err,error_class="retryable",str(exc),"bootstrap_timeout" if "bootstrap" in str(exc) else "timeout"
        except Exception as exc: state,err,error_class="failed",str(exc),"tool_runtime_failed"
        retry_count = self.store.conn.execute("SELECT retry_count FROM runs WHERE id=?", (run_id,)).fetchone()[0]
        if state != "succeeded" and retry_count >= self.config.max_retries:
            state = "failed"
            error_class = "retry_budget_exhausted"
        self.store.conn.execute("UPDATE runs SET retry_count=? WHERE id=? AND generation=?", (retry_count + (state != "succeeded"), run_id, generation))
        self.store.finish_run(run_id, generation, state, err, error_class)
        self.store.release_fenced(iid, owner, run_id, generation, lease_epoch)
        if state == "retryable":
            self.store.event("requeued", iid, run_id, generation, {"error_class": error_class})
        return state
    def run(self, issue_id=None):
        """Run up to configured concurrency, returning per-issue outcomes."""
        ids = [issue_id] if issue_id is not None else self.store.pending_issue_ids()[:max(1, self.config.concurrency)]
        return {iid: self.run_once(iid) for iid in ids}

    def recover(self, dry_run=False):
        return self.store.recover(dry_run=dry_run)

    def startup_preflight(self):
        return self.store.startup_preflight(self.owner)

    def recover_accepted_idle(self, now=None, dry_run=False):
        return self.store.accepted_idle_recovery(
            time.time() if now is None else now,
            self.config.accepted_idle_alert_after,
            self.config.accepted_idle_fence_after,
            self.config.accepted_idle_retries,
            dry_run,
        )

    def _execute(self, command, issue_id):
        formatted_command = command.format(issue_id=issue_id)
        proc=subprocess.Popen(formatted_command, shell=True, start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        started=last=time.monotonic()
        while proc.poll() is None:
            time.sleep(.05)
            if time.monotonic()-started > self.config.hard_timeout or time.monotonic()-last > self.config.no_progress_timeout:
                os.killpg(proc.pid, signal.SIGTERM)
                try: proc.wait(2)
                except subprocess.TimeoutExpired: os.killpg(proc.pid, signal.SIGKILL); proc.wait()
                raise TimeoutError("worker timeout")
        return proc.returncode

def main(argv=None):
    p=argparse.ArgumentParser(prog="task-runner"); p.add_argument("--db",type=Path,default=None); sub=p.add_subparsers(dest="command",required=True)
    scan=sub.add_parser("scan")
    scan.add_argument("--dry-run",action="store_true", help="fetch issues without changing the local store")
    r=sub.add_parser("run-once", help="select one queued issue and run its worker")
    r.add_argument("--issue",type=int)
    r.add_argument("--dry-run",action="store_true", help="show selected candidates without claiming or running them")
    sub.add_parser("status")
    rec=sub.add_parser("recover")
    rec.add_argument("--dry-run",action="store_true")
    idle=sub.add_parser("recover-accepted-idle", help="alert and fence unready accepted runs")
    idle.add_argument("--dry-run",action="store_true")
    sub.add_parser("preflight", help="fail-closed coordinator startup checks")
    reconcile=sub.add_parser("reconcile", help="report and quarantine ambiguous non-terminal records")
    reconcile.add_argument("--worktree", type=Path)
    heartbeat=sub.add_parser("heartbeat", help="repair parent rollups and merged completion evidence")
    heartbeat.add_argument("--dry-run", action="store_true")
    args=p.parse_args(argv); dry_run=args.command == "run-once" and args.dry_run; cfg=RunnerConfig(db=args.db or RunnerConfig().db); store=TaskStore(cfg.db, readonly=dry_run); runner=Runner(cfg, store=store)
    if args.command == "run-once": result=runner.run_once(args.issue, dry_run=dry_run)
    elif args.command == "recover": result=runner.recover(dry_run=args.dry_run)
    elif args.command == "recover-accepted-idle": result=runner.recover_accepted_idle(dry_run=args.dry_run)
    elif args.command == "preflight":
        result=runner.startup_preflight()
        if not result["ok"]:
            print(json.dumps(result, indent=2, default=str)); return 2
    elif args.command == "scan": result=runner.scan(dry_run=args.dry_run)
    elif args.command == "reconcile": result=store.reconcile(args.worktree)
    elif args.command == "heartbeat": result=runner.heartbeat(dry_run=args.dry_run)
    else: result=getattr(runner,args.command)()
    print(json.dumps(result,indent=2,default=str)); return 0
if __name__ == "__main__": raise SystemExit(main())
