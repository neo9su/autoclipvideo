import sqlite3
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))
from runner.ops.task_runner import Runner, RunnerConfig, TaskStore


def test_lease_uniqueness(tmp_path):
    s=TaskStore(tmp_path/'x.db'); s.upsert_issue(1,'x')
    assert s.claim(1,'a',60)
    assert not s.claim(1,'b',60)
    assert s.claim(1,'a',60)


def test_restart_recovery(tmp_path):
    s=TaskStore(tmp_path/'x.db'); s.upsert_issue(1,'x'); s.claim(1,'a',-1)
    s.conn.execute("INSERT INTO runs VALUES ('r',1,'running',?,?,?)",(time.time(),None,None))
    got=s.recover(); assert got=={'expired_leases':1,'interrupted_runs':1,'dry_run':False}
    assert s.conn.execute("SELECT state FROM runs").fetchone()[0]=='interrupted'
    assert s.conn.execute("SELECT state FROM issues").fetchone()[0]=='retryable'


def test_idempotent_run_once(tmp_path):
    s=TaskStore(tmp_path/'x.db'); s.upsert_issue(1,'x'); calls=[]
    r=Runner(RunnerConfig(db=tmp_path/'x.db'),s,worker=lambda issue: calls.append(issue['id']) or 0)
    assert r.run_once()== 'succeeded'; assert r.run_once() is None; assert calls==[1]


def test_timeout_terminates_worker(tmp_path):
    s=TaskStore(tmp_path/'x.db'); s.upsert_issue(1,'x')
    cfg=RunnerConfig(db=tmp_path/'x.db', worker_command='sleep 30', hard_timeout=.1, no_progress_timeout=.1)
    assert Runner(cfg,s).run_once() == 'retryable'


def test_status_api_returns_store_state(tmp_path):
    s=TaskStore(tmp_path/'x.db'); s.upsert_issue(1, 'x')
    assert Runner(RunnerConfig(db=tmp_path/'x.db'), s).status()['issues'][0]['id'] == 1


def test_scan_dry_run_does_not_persist(tmp_path):
    class Adapter:
        def scan(self): return [{'number': 7, 'title': 'remote'}]
    s=TaskStore(tmp_path/'x.db')
    runner=Runner(RunnerConfig(db=tmp_path/'x.db'), s, adapter=Adapter())
    assert runner.scan(dry_run=True) == [{'number': 7, 'title': 'remote'}]
    assert s.status()['issues'] == []


def test_cli_status_and_recover_dry_run(tmp_path):
    db=tmp_path/'x.db'
    command=[sys.executable, '-m', 'runner.ops.task_runner', '--db', str(db)]
    status=subprocess.run(command+['status'], capture_output=True, text=True, check=True)
    assert json.loads(status.stdout) == {'issues': [], 'runs': [], 'leases': [], 'events': 0}
    recover=subprocess.run(command+['recover', '--dry-run'], capture_output=True, text=True, check=True)
    assert json.loads(recover.stdout) == {'expired_leases': 0, 'interrupted_runs': 0, 'dry_run': True}
