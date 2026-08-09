import sqlite3
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))
from runner.ops.task_runner import Runner, RunnerConfig, TaskStore
from runner.ops.worktree_contract import WorktreeContractError, WorktreeProfile


def test_lease_uniqueness(tmp_path):
    s=TaskStore(tmp_path/'x.db'); s.upsert_issue(1,'x')
    assert s.claim(1,'a',60)
    assert not s.claim(1,'b',60)
    assert s.claim(1,'a',60)


def test_restart_recovery(tmp_path):
    s=TaskStore(tmp_path/'x.db'); s.upsert_issue(1,'x'); s.claim(1,'a',-1)
    s.conn.execute("INSERT INTO runs(id,issue_id,state,started_at,finished_at,error) VALUES ('r',1,'running',?,?,?)",(time.time(),None,None))
    got=s.recover(); assert got=={'expired_leases':1,'interrupted_runs':1,'accepted_idle':0,'dry_run':False}
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
    assert json.loads(recover.stdout) == {'expired_leases': 0, 'interrupted_runs': 0, 'accepted_idle': 0, 'dry_run': True}


def test_run_has_generation_and_fenced_late_event(tmp_path):
    store = TaskStore(tmp_path / 'x.db')
    store.upsert_issue(9, 'generation')
    assert Runner(RunnerConfig(db=tmp_path / 'x.db'), store, worker=lambda issue: 0).run_once() == 'succeeded'
    run = store.conn.execute('SELECT id,generation FROM runs WHERE issue_id=9').fetchone()
    assert run['generation'] == 1
    assert not store.fenced_event('first_tool_activity', 9, run['id'], 0)
    assert store.conn.execute("SELECT kind FROM events ORDER BY id DESC LIMIT 1").fetchone()[0] == 'late_event_ignored'


def test_single_flight_prevents_nested_tick(tmp_path):
    store = TaskStore(tmp_path / 'x.db')
    with store.single_flight('first') as acquired:
        assert acquired
        with store.single_flight('second') as nested:
            assert not nested


def test_worktree_contract_rejects_main_checkout(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    subprocess.run(['git', '-C', str(repo), 'config', 'user.email', 'test@example.invalid'], check=True)
    subprocess.run(['git', '-C', str(repo), 'config', 'user.name', 'Test'], check=True)
    (repo / 'README').write_text('test')
    subprocess.run(['git', '-C', str(repo), 'add', 'README'], check=True)
    subprocess.run(['git', '-C', str(repo), 'commit', '-qm', 'initial'], check=True)
    with __import__('pytest').raises(WorktreeContractError):
        WorktreeProfile(repo, repo).validate()


def test_worktree_contract_accepts_canonical_sibling_worktree(tmp_path):
    repo = tmp_path / 'repo'
    worktree = tmp_path / 'repo.worktrees' / 'feature'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    subprocess.run(['git', '-C', str(repo), 'config', 'user.email', 'test@example.invalid'], check=True)
    subprocess.run(['git', '-C', str(repo), 'config', 'user.name', 'Test'], check=True)
    (repo / 'README').write_text('test')
    subprocess.run(['git', '-C', str(repo), 'add', 'README'], check=True)
    subprocess.run(['git', '-C', str(repo), 'commit', '-qm', 'initial'], check=True)
    subprocess.run(['git', '-C', str(repo), 'worktree', 'add', '-q', '-b', 'feature', str(worktree)], check=True)

    metadata = WorktreeProfile(worktree, repo).validate()

    assert metadata['cwd'] == str(worktree.resolve())
    assert metadata['repo_root'] == str(worktree.resolve())
    assert metadata['branch'] == 'feature'
    assert len(metadata['head_sha']) == 40


def test_worktree_contract_rejects_unrelated_sibling(tmp_path):
    repo = tmp_path / 'repo'
    unrelated = tmp_path / 'other.worktrees' / 'feature'
    repo.mkdir()
    unrelated.mkdir(parents=True)

    with __import__('pytest').raises(WorktreeContractError):
        WorktreeProfile(unrelated, repo).validate()
