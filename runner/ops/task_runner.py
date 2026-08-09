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
CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, issue_id INTEGER NOT NULL, state TEXT NOT NULL, started_at REAL NOT NULL, finished_at REAL, error TEXT, generation INTEGER NOT NULL DEFAULT 1, lease_epoch INTEGER NOT NULL DEFAULT 1, session_key TEXT, retry_count INTEGER NOT NULL DEFAULT 0, error_class TEXT, last_seq INTEGER NOT NULL DEFAULT 0, UNIQUE(issue_id, id));
CREATE TABLE IF NOT EXISTS leases (issue_id INTEGER PRIMARY KEY, owner TEXT NOT NULL, expires_at REAL NOT NULL, run_id TEXT, generation INTEGER NOT NULL DEFAULT 1, lease_epoch INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS sessions (run_id TEXT PRIMARY KEY, generation INTEGER NOT NULL, session_key TEXT NOT NULL UNIQUE, state TEXT NOT NULL, confirmed_at REAL, last_activity_at REAL);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_uuid TEXT NOT NULL UNIQUE, seq INTEGER, kind TEXT NOT NULL, issue_id INTEGER, run_id TEXT, generation INTEGER, lease_epoch INTEGER, payload TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, alert_key TEXT NOT NULL UNIQUE, issue_id INTEGER, run_id TEXT, kind TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'open', created_at REAL NOT NULL, payload TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS coordinator_lock (name TEXT PRIMARY KEY, owner TEXT NOT NULL, acquired_at REAL NOT NULL);
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
    accepted_idle_alert_after: float = float(os.getenv("TASK_RUNNER_ACCEPTED_IDLE_ALERT", "120"))
    accepted_idle_fence_after: float = float(os.getenv("TASK_RUNNER_ACCEPTED_IDLE_FENCE", "180"))

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
        for name, definition in (("generation", "INTEGER NOT NULL DEFAULT 1"), ("lease_epoch", "INTEGER NOT NULL DEFAULT 1"), ("session_key", "TEXT"), ("retry_count", "INTEGER NOT NULL DEFAULT 0"), ("error_class", "TEXT"), ("last_seq", "INTEGER NOT NULL DEFAULT 0")):
            if name not in columns:
                self.conn.execute(f"ALTER TABLE runs ADD COLUMN {name} {definition}")
        event_columns = {row[1] for row in self.conn.execute("PRAGMA table_info(events)")}
        for name, definition in (("event_uuid", "TEXT"), ("seq", "INTEGER"), ("generation", "INTEGER"), ("lease_epoch", "INTEGER")):
            if name not in event_columns:
                self.conn.execute(f"ALTER TABLE events ADD COLUMN {name} {definition}")
        self.conn.execute("UPDATE events SET event_uuid=lower(hex(randomblob(16))) WHERE event_uuid IS NULL")
        self.conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS events_event_uuid_idx ON events(event_uuid)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, alert_key TEXT NOT NULL UNIQUE, issue_id INTEGER, run_id TEXT, kind TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'open', created_at REAL NOT NULL, payload TEXT NOT NULL DEFAULT '{}')")
        self.conn.execute("CREATE TABLE IF NOT EXISTS coordinator_lock (name TEXT PRIMARY KEY, owner TEXT NOT NULL, acquired_at REAL NOT NULL)")

        lease_columns = {row[1] for row in self.conn.execute("PRAGMA table_info(leases)")}
        for name, definition in (("run_id", "TEXT"), ("generation", "INTEGER NOT NULL DEFAULT 1")):
            if name not in lease_columns:
                self.conn.execute(f"ALTER TABLE leases ADD COLUMN {name} {definition}")

    def close(self): self.conn.close()

    def preflight(self) -> dict[str, object]:
        """Require writable persistent state and a single coordinator owner."""
        if self.readonly or not os.access(self.db.parent, os.W_OK):
            raise RuntimeError("coordinator state is not writable")
        if not self.acquire_single_flight(self.db.stem):
            raise RuntimeError("another coordinator is already active")
        return {"ok": True, "single_flight": True}


    def acquire_single_flight(self, owner: str) -> bool:
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            self.conn.execute("INSERT INTO coordinator_lock(name,owner,acquired_at) VALUES('coordinator',?,?)", (owner, time.time()))
            self.conn.execute("COMMIT")
            return True
        except sqlite3.IntegrityError:
            if self.conn.in_transaction: self.conn.execute("ROLLBACK")
            return False

    def release_single_flight(self, owner: str) -> None:
        self.conn.execute("DELETE FROM coordinator_lock WHERE name='coordinator' AND owner=?", (owner,))

    def acquire_single_flight(self, owner: str) -> bool:
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            self.conn.execute("INSERT INTO coordinator_lock(name,owner,acquired_at) VALUES('coordinator',?,?)", (owner, time.time()))
            self.conn.execute("COMMIT")
            return True
        except sqlite3.IntegrityError:
            if self.conn.in_transaction: self.conn.execute("ROLLBACK")
            return False

    def release_single_flight(self, owner: str) -> None:
        self.conn.execute("DELETE FROM coordinator_lock WHERE name='coordinator' AND owner=?", (owner,))

    def reconcile(self, dry_run=False):
        """Report local truth mismatches and quarantine ambiguous issues."""
        report = []
        for issue in self.conn.execute("SELECT id,state FROM issues WHERE state NOT IN ('done','closed')"):
            run = self.conn.execute("SELECT id,generation,state FROM runs WHERE issue_id=? ORDER BY started_at DESC LIMIT 1", (issue[0],)).fetchone()
            lease = self.conn.execute("SELECT run_id,generation FROM leases WHERE issue_id=?", (issue[0],)).fetchone()
            ambiguous = bool(run and lease and (run[0] != lease[0] or run[1] != lease[1])) or (issue[1] in {'running','accepted_idle'} and not run)
            item = {"issue_id": issue[0], "issue_state": issue[1], "run": dict(run) if run else None, "lease": dict(lease) if lease else None, "ambiguous": ambiguous}
            report.append(item)
            if ambiguous and not dry_run:
                self.conn.execute("UPDATE issues SET state='recovery_needed',updated_at=? WHERE id=?", (time.time(), issue[0]))
                self.event("quarantined", issue_id=issue[0], payload={"reason": "lifecycle truth mismatch"})
        return {"issues": report, "dry_run": dry_run}
    def reconcile_accepted_idle(self, now=None, alert_after=120, fence_after=180, max_retries=1, dry_run=False):
        now = time.time() if now is None else now
        rows = self.conn.execute("SELECT id,issue_id,generation,retry_count,started_at FROM runs WHERE state='accepted_idle'").fetchall()
        alerts = fenced = 0
        for run_id, issue_id, generation, retries, started_at in rows:
            age = max(0.0, now - started_at)
            if age >= alert_after and not dry_run:
                key = f"accepted_idle:{run_id}:alert"
                changed = self.conn.execute("INSERT OR IGNORE INTO alerts(alert_key,issue_id,run_id,kind,created_at,payload) VALUES(?,?,?,?,?,?)", (key, issue_id, run_id, "accepted_idle", now, json.dumps({"age_seconds": age}))).rowcount
                alerts += int(changed)
            if age >= fence_after:
                fenced += 1
                if not dry_run:
                    next_state = "retryable" if retries < max_retries else "recovery_needed"
                    self.conn.execute("UPDATE runs SET state=?,finished_at=?,error=?,error_class=?,retry_count=retry_count+1 WHERE id=? AND generation=? AND state='accepted_idle'", (next_state, now, "worker readiness was not verified", "accepted_idle_timeout", run_id, generation))
                    self.conn.execute("UPDATE issues SET state=?,updated_at=? WHERE id=? AND state='accepted_idle'", (next_state, now, issue_id))
                    self.conn.execute("DELETE FROM leases WHERE issue_id=? AND run_id=? AND generation=?", (issue_id, run_id, generation))
                    self.event("accepted_idle_fenced", issue_id, run_id, generation, {"next_state": next_state})
        return {"accepted_idle": len(rows), "alerts": alerts, "fenced": fenced, "dry_run": dry_run}

    def event(self, kind, issue_id=None, run_id=None, generation=None, payload=None, lease_epoch=None, seq=None):
        self.conn.execute("INSERT INTO events(event_uuid,seq,kind,issue_id,run_id,generation,lease_epoch,payload,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (str(uuid.uuid4()), seq, kind, issue_id, run_id, generation, lease_epoch, json.dumps(payload or {}), time.time()))


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
        if existing and existing[0] in {"done", "running"}:
            state = existing[0]
        self.conn.execute("INSERT INTO issues(id,title,state,payload,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,payload=excluded.payload,updated_at=excluded.updated_at", (issue_id,title,state,json.dumps(payload or {}),now))
    def claim(self, issue_id, owner, ttl, run_id=None, generation=1):
        now=time.time(); self.conn.execute("BEGIN IMMEDIATE")
        try:
            row=self.conn.execute("SELECT owner,expires_at FROM leases WHERE issue_id=?",(issue_id,)).fetchone()
            if row and row[1] > now and row[0] != owner: self.conn.execute("ROLLBACK"); return False
            self.conn.execute("INSERT INTO leases(issue_id,owner,expires_at,run_id,generation,lease_epoch) VALUES(?,?,?,?,?,?) ON CONFLICT(issue_id) DO UPDATE SET owner=excluded.owner,expires_at=excluded.expires_at,run_id=excluded.run_id,generation=excluded.generation,lease_epoch=excluded.lease_epoch",(issue_id,owner,now+ttl,run_id,generation,generation)); self.conn.execute("COMMIT"); self.event("lease_acquired",issue_id,run_id,generation,{"owner":owner}, lease_epoch=generation); return True
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
    def status(self):
        return {"issues": [dict(x) for x in self.conn.execute("SELECT * FROM issues ORDER BY id")], "runs": [dict(x) for x in self.conn.execute("SELECT * FROM runs ORDER BY started_at DESC")], "leases": [dict(x) for x in self.conn.execute("SELECT * FROM leases")], "sessions": [dict(x) for x in self.conn.execute("SELECT * FROM sessions")], "alerts": [dict(x) for x in self.conn.execute("SELECT * FROM alerts ORDER BY created_at DESC")], "events": self.conn.execute("SELECT count(*) FROM events").fetchone()[0]}

    def pending_issue_ids(self):
        return [row[0] for row in self.conn.execute("SELECT id FROM issues WHERE state IN ('queued','retryable') ORDER BY id")]


class GitHubAdapter:
    def __init__(self, command="gh"): self.command=command
    def scan(self):
        try:
            out=subprocess.check_output([self.command,"issue","list","--json","number,title,state","--state","open"], text=True)
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
        return issues

    def preflight(self):
        return self.store.preflight()

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
        self.store.conn.execute("INSERT INTO runs(id,issue_id,state,started_at,generation,session_key,retry_count) VALUES(?,?,?,?,?,?,?)",(run_id,iid,"running",now,generation,session_key,prior_failures)); self.store.conn.execute("INSERT INTO sessions(run_id,generation,session_key,state) VALUES(?,?,?,?)",(run_id,generation,session_key,"requested")); self.store.event("session_requested",iid,run_id,generation)
        self.store.conn.execute("UPDATE issues SET state='accepted_idle',updated_at=? WHERE id=?",(now,iid))
        try:
            if not self.store.confirm_session(run_id, generation):
                raise TimeoutError("session confirmation timeout")
            if not self.store.mark_bootstrap(run_id, generation):
                raise TimeoutError("bootstrap timeout")
            self.store.record_activity(run_id, generation)
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
        self.store.release(iid, owner, run_id, generation)
        if state == "retryable":
            self.store.event("requeued", iid, run_id, generation, {"error_class": error_class})
        return state
    def run(self, issue_id=None):
        """Run up to configured concurrency, returning per-issue outcomes."""
        ids = [issue_id] if issue_id is not None else self.store.pending_issue_ids()[:max(1, self.config.concurrency)]
        return {iid: self.run_once(iid) for iid in ids}

    def recover(self, dry_run=False):
        return self.store.recover(dry_run=dry_run)

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
    idle=sub.add_parser("reconcile-accepted-idle")
    idle.add_argument("--dry-run", action="store_true")
    rec=sub.add_parser("recover")
    rec.add_argument("--dry-run",action="store_true")
    args=p.parse_args(argv); dry_run=args.command == "run-once" and args.dry_run; cfg=RunnerConfig(db=args.db or RunnerConfig().db); store=TaskStore(cfg.db, readonly=dry_run); runner=Runner(cfg, store=store)
    if args.command == "run-once": result=runner.run_once(args.issue, dry_run=dry_run)
    elif args.command == "recover": result=runner.recover(dry_run=args.dry_run)
    elif args.command == "scan": result=runner.scan(dry_run=args.dry_run)
    elif args.command == "reconcile-accepted-idle": result=runner.store.reconcile_accepted_idle(alert_after=cfg.accepted_idle_alert_after, fence_after=cfg.accepted_idle_fence_after, max_retries=1, dry_run=args.dry_run)
    else: result=getattr(runner,args.command)()
    print(json.dumps(result,indent=2,default=str)); return 0
if __name__ == "__main__": raise SystemExit(main())
