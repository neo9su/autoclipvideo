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
CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, issue_id INTEGER NOT NULL, state TEXT NOT NULL, started_at REAL NOT NULL, finished_at REAL, error TEXT, UNIQUE(issue_id, id));
CREATE TABLE IF NOT EXISTS leases (issue_id INTEGER PRIMARY KEY, owner TEXT NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, issue_id INTEGER, run_id TEXT, payload TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL);
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
        elif not self.db.exists():
            self.conn.executescript(SCHEMA)

    def close(self): self.conn.close()
    def event(self, kind, issue_id=None, run_id=None, payload=None):
        self.conn.execute("INSERT INTO events(kind,issue_id,run_id,payload,created_at) VALUES(?,?,?,?,?)", (kind, issue_id, run_id, json.dumps(payload or {}), time.time()))
    def upsert_issue(self, issue_id, title, state="queued", payload=None):
        now = time.time()
        existing = self.conn.execute("SELECT state FROM issues WHERE id=?", (issue_id,)).fetchone()
        if existing and existing[0] in {"done", "running"}:
            state = existing[0]
        self.conn.execute("INSERT INTO issues(id,title,state,payload,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,payload=excluded.payload,updated_at=excluded.updated_at", (issue_id,title,state,json.dumps(payload or {}),now))
    def claim(self, issue_id, owner, ttl):
        now=time.time(); self.conn.execute("BEGIN IMMEDIATE")
        try:
            row=self.conn.execute("SELECT owner,expires_at FROM leases WHERE issue_id=?",(issue_id,)).fetchone()
            if row and row[1] > now and row[0] != owner: self.conn.execute("ROLLBACK"); return False
            self.conn.execute("INSERT INTO leases(issue_id,owner,expires_at) VALUES(?,?,?) ON CONFLICT(issue_id) DO UPDATE SET owner=excluded.owner,expires_at=excluded.expires_at",(issue_id,owner,now+ttl)); self.conn.execute("COMMIT"); self.event("lease_acquired",issue_id,payload={"owner":owner}); return True
        except Exception: self.conn.execute("ROLLBACK"); raise
    def release(self, issue_id, owner): self.conn.execute("DELETE FROM leases WHERE issue_id=? AND owner=?",(issue_id,owner))
    def recover(self, now=None, dry_run=False):
        now=time.time() if now is None else now; expired=self.conn.execute("SELECT issue_id,owner FROM leases WHERE expires_at<=?",(now,)).fetchall(); running=self.conn.execute("SELECT id,issue_id FROM runs WHERE state='running'").fetchall()
        if not dry_run:
            for r in expired: self.conn.execute("DELETE FROM leases WHERE issue_id=?",(r[0],)); self.event("lease_expired",r[0])
            for r in running: self.conn.execute("UPDATE runs SET state='interrupted',finished_at=?,error=? WHERE id=?",(now,"runner restart recovery",r[0])); self.conn.execute("UPDATE issues SET state='retryable',updated_at=? WHERE id=?",(now,r[1])); self.event("run_interrupted",r[1],r[0])
        return {"expired_leases":len(expired),"interrupted_runs":len(running),"dry_run":dry_run}
    def status(self):
        return {"issues": [dict(x) for x in self.conn.execute("SELECT * FROM issues ORDER BY id")], "runs": [dict(x) for x in self.conn.execute("SELECT * FROM runs ORDER BY started_at DESC")], "leases": [dict(x) for x in self.conn.execute("SELECT * FROM leases")], "events": self.conn.execute("SELECT count(*) FROM events").fetchone()[0]}

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
    def scan(self, dry_run=False):
        issues=self.adapter.scan()
        if not dry_run:
            for i in issues:
                number = i.get("number")
                title = i.get("title", f"Issue {number}")
                if number is not None: self.store.upsert_issue(number, title, "queued", i)
        return issues

    def status(self):
        """Return the persisted runner state for the CLI and API callers."""
        return self.store.status()
    def run_once(self, issue_id=None, dry_run=False):
        rows=self.store.conn.execute("SELECT id,title,payload FROM issues WHERE state IN ('queued','retryable') AND (? IS NULL OR id=?) ORDER BY id",(issue_id,issue_id)).fetchall()
        if dry_run:
            return {"dry_run": True, "candidates": [{"id": row[0], "title": row[1], "payload": json.loads(row[2])} for row in rows]}
        if not rows: return None
        issue=rows[0]; owner=f"{os.uname().nodename}:{os.getpid()}"; iid=issue[0]
        if not self.store.claim(iid,owner,self.config.lease_seconds): return None
        run_id=str(uuid.uuid4()); now=time.time(); self.store.conn.execute("INSERT INTO runs(id,issue_id,state,started_at) VALUES(?,?,?,?)",(run_id,iid,"running",now)); self.store.conn.execute("UPDATE issues SET state='running',updated_at=? WHERE id=?",(now,iid))
        try:
            if self.worker: result=self.worker(dict(issue))
            elif self.config.worker_command: result=self._execute(self.config.worker_command, iid)
            else: result=0
            state="succeeded" if result in (None,0,True) else "failed"; err=None if state=="succeeded" else str(result)
        except TimeoutError as exc: state,err="retryable",str(exc)
        except Exception as exc: state,err="failed",str(exc)
        self.store.conn.execute("UPDATE runs SET state=?,finished_at=?,error=? WHERE id=?",(state,time.time(),err,run_id)); self.store.conn.execute("UPDATE issues SET state=?,updated_at=? WHERE id=?",("done" if state=="succeeded" else "retryable",time.time(),iid)); self.store.release(iid,owner); self.store.event("run_finished",iid,run_id,{"state":state}); return state
    def run(self, issue_id=None):
        """Run up to configured concurrency, returning per-issue outcomes."""
        ids = [issue_id] if issue_id is not None else self.store.pending_issue_ids()[:max(1, self.config.concurrency)]
        return {iid: self.run_once(iid) for iid in ids}

    def recover(self, dry_run=False):
        return self.store.recover(dry_run=dry_run)

    def _execute(self, command, issue_id):
        proc=subprocess.Popen(command.format(issue_id=issue_id), shell=True, start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
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
    args=p.parse_args(argv); dry_run=args.command == "run-once" and args.dry_run; cfg=RunnerConfig(db=args.db or RunnerConfig().db); store=TaskStore(cfg.db, readonly=dry_run); runner=Runner(cfg, store=store)
    if args.command == "run-once": result=runner.run_once(args.issue, dry_run=dry_run)
    elif args.command == "recover": result=runner.recover(dry_run=args.dry_run)
    elif args.command == "scan": result=runner.scan(dry_run=args.dry_run)
    else: result=getattr(runner,args.command)()
    print(json.dumps(result,indent=2,default=str)); return 0
if __name__ == "__main__": raise SystemExit(main())
