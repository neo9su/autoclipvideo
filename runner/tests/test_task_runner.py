import sqlite3
import json
import subprocess
import sys
import time
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))
from runner.ops.task_runner import Runner, RunnerConfig, TaskStore
from runner.ops.worktree_contract import WorktreeContract, WorktreeContractError


def test_lease_uniqueness(tmp_path):
    s=TaskStore(tmp_path/'x.db'); s.upsert_issue(1,'x')
    assert s.claim(1,'a',60)
    assert not s.claim(1,'b',60)
    assert s.claim(1,'a',60)


def test_restart_recovery(tmp_path):
    s=TaskStore(tmp_path/'x.db'); s.upsert_issue(1,'x'); s.claim(1,'a',-1)
    s.conn.execute("INSERT INTO runs(id,issue_id,state,started_at,finished_at,error) VALUES ('r',1,'running',?,?,?)",(time.time(),None,None))
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


def test_run_once_dry_run_does_not_claim_or_start_worker(tmp_path):
    db=tmp_path/'x.db'; s=TaskStore(db); s.upsert_issue(3, 'queued issue'); s.upsert_issue(4, 'retryable issue', 'retryable')
    calls=[]
    runner=Runner(RunnerConfig(db=db), s, worker=lambda issue: calls.append(issue['id']) or 0)
    before=s.status()
    result=runner.run_once(dry_run=True)
    assert result == {'dry_run': True, 'candidates': [
        {'id': 3, 'title': 'queued issue', 'payload': {}},
        {'id': 4, 'title': 'retryable issue', 'payload': {}},
    ]}
    assert s.status() == before
    assert calls == []


def test_run_once_dry_run_issue_filter_is_read_only(tmp_path):
    db = tmp_path / 'x.db'
    store = TaskStore(db)
    store.upsert_issue(3, 'queued issue')
    store.upsert_issue(4, 'retryable issue', 'retryable')
    before = store.status()

    result = Runner(RunnerConfig(db=db), store).run_once(issue_id=4, dry_run=True)

    assert result == {'dry_run': True, 'candidates': [
        {'id': 4, 'title': 'retryable issue', 'payload': {}},
    ]}
    assert store.status() == before


def test_cli_run_once_dry_run_reports_candidates_without_creating_db(tmp_path):
    db=tmp_path/'missing'/'runner.sqlite3'
    command=[sys.executable, '-m', 'runner.ops.task_runner', '--db', str(db), 'run-once', '--dry-run']
    result=subprocess.run(command, capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == {'dry_run': True, 'candidates': []}
    assert not db.exists()


def test_cli_status_and_recover_dry_run(tmp_path):
    db=tmp_path/'x.db'
    command=[sys.executable, '-m', 'runner.ops.task_runner', '--db', str(db)]
    status=subprocess.run(command+['status'], capture_output=True, text=True, check=True)
    assert json.loads(status.stdout) == {'issues': [], 'runs': [], 'leases': [], 'events': 0}
    recover=subprocess.run(command+['recover', '--dry-run'], capture_output=True, text=True, check=True)
    assert json.loads(recover.stdout) == {'expired_leases': 0, 'interrupted_runs': 0, 'dry_run': True}


def test_run_has_generation_and_session_lifecycle(tmp_path):
    store = TaskStore(tmp_path / 'x.db')
    store.upsert_issue(9, 'lifecycle')
    assert Runner(RunnerConfig(db=tmp_path / 'x.db'), store, worker=lambda issue: 0).run_once() == 'succeeded'
    run = store.conn.execute('SELECT id,generation,session_key FROM runs').fetchone()
    assert run['generation'] == 1 and run['session_key'].startswith('issue:9:run:')
    kinds = [row[0] for row in store.conn.execute('SELECT kind FROM events ORDER BY id')]
    assert kinds[:3] == ['lease_acquired', 'session_requested', 'session_confirmed']


def test_late_generation_activity_is_fenced(tmp_path):
    store = TaskStore(tmp_path / 'x.db')
    store.upsert_issue(1, 'fence')
    Runner(RunnerConfig(db=tmp_path / 'x.db'), store, worker=lambda issue: 0).run_once()
    run_id = store.conn.execute('SELECT id FROM runs').fetchone()[0]
    assert not store.record_activity(run_id, 2)
    assert store.conn.execute("SELECT state FROM sessions WHERE run_id=?", (run_id,)).fetchone()[0] == 'active'


def test_finish_run_fences_completed_and_stale_generations(tmp_path):
    store = TaskStore(tmp_path / 'x.db')
    store.upsert_issue(1, 'fence finish')
    runner = Runner(RunnerConfig(db=tmp_path / 'x.db'), store, worker=lambda issue: 0)
    assert runner.run_once() == 'succeeded'
    run = store.conn.execute('SELECT id,generation,state FROM runs').fetchone()
    assert not store.finish_run(run['id'], run['generation'], 'succeeded')
    assert not store.finish_run(run['id'], run['generation'] + 1, 'succeeded')
    assert store.conn.execute('SELECT state FROM issues WHERE id=1').fetchone()[0] == 'done'


def test_retry_generation_increments_for_same_issue(tmp_path):
    store = TaskStore(tmp_path / 'x.db')
    store.upsert_issue(1, 'generation')
    runner = Runner(RunnerConfig(db=tmp_path / 'x.db'), store, worker=lambda issue: 1)
    assert runner.run_once() == 'failed'
    assert runner.run_once() == 'failed'
    generations = [row[0] for row in store.conn.execute('SELECT generation FROM runs ORDER BY started_at')]
    assert generations == [1, 2]


def test_worktree_contract_rejects_wrong_branch(tmp_path):
    contract = WorktreeContract(tmp_path / 'assigned', tmp_path, 'feature/118')
    with pytest.raises(WorktreeContractError):
        contract.validate(tmp_path / 'assigned', tmp_path, 'master')


def test_session_confirmation_and_bootstrap_are_fenced(tmp_path):
    store = TaskStore(tmp_path / 'x.db')
    store.upsert_issue(1, 'lifecycle')
    assert store.claim(1, 'owner', 60, 'run-1', 1)
    store.conn.execute(
        "INSERT INTO runs(id,issue_id,state,started_at,generation,session_key) VALUES(?,?,?,?,?,?)",
        ('run-1', 1, 'accepted_idle', time.time(), 1, 'session-1'),
    )
    store.conn.execute(
        "INSERT INTO sessions(run_id,generation,session_key,state) VALUES(?,?,?,?)",
        ('run-1', 1, 'session-1', 'requested'),
    )
    assert store.confirm_session('run-1', 1)
    assert store.mark_bootstrap('run-1', 1)
    assert not store.confirm_session('run-1', 2)
    assert not store.mark_bootstrap('run-1', 2)
    assert store.record_activity('run-1', 1)


def test_late_lease_release_cannot_remove_new_generation(tmp_path):
    store = TaskStore(tmp_path / 'x.db')
    assert store.claim(1, 'owner-a', 60, 'run-a', 1)
    assert store.claim(1, 'owner-b', 60, 'run-b', 2) is False
    store.conn.execute(
        "UPDATE leases SET owner='owner-b',run_id='run-b',generation=2 WHERE issue_id=1"
    )
    store.release(1, 'owner-a', 'run-a', 1)
    lease = store.conn.execute('SELECT owner,run_id,generation FROM leases').fetchone()
    assert tuple(lease) == ('owner-b', 'run-b', 2)


def test_recovery_reclaims_accepted_idle_and_fences_late_finish(tmp_path):
    store = TaskStore(tmp_path / 'x.db')
    store.upsert_issue(1, 'recovery')
    store.claim(1, 'owner', -1, 'run-1', 1)
    store.conn.execute(
        "INSERT INTO runs(id,issue_id,state,started_at,generation,session_key) VALUES(?,?,?,?,?,?)",
        ('run-1', 1, 'accepted_idle', time.time(), 1, 'session-1'),
    )
    assert store.recover()['interrupted_runs'] == 1
    assert not store.finish_run('run-1', 1, 'succeeded')
    assert store.conn.execute('SELECT state FROM issues WHERE id=1').fetchone()[0] == 'retryable'
