import importlib.util
from pathlib import Path
import sqlite3

import pytest

spec = importlib.util.spec_from_file_location('activation', Path(__file__).parents[1] / 'scripts/activate_remote_audio.py')
activation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(activation)


@pytest.fixture
def idle(tmp_path, monkeypatch):
    path = tmp_path / 'jobs.db'
    connect = sqlite3.connect
    with connect(path) as db:
        for table in ['jobs', 'clip_jobs', 'tts_jobs', 'concat_jobs']:
            db.execute(f'create table {table}(status text)')
            db.execute(f"insert into {table} values ('done')")
    health = dict(pid=123, gpu_busy=False, queue_depth=0, clip_jobs_running=0,
                  clip_jobs_pending=0, concat_jobs_active=0, classic_concat_jobs_active=0)
    def request(port, route, **kwargs):
        return health if route == '/health' else {'status': 'done'}
    monkeypatch.setattr(activation, 'request', request)
    monkeypatch.setattr(activation.sqlite3, 'connect', lambda _: connect(path))
    return health, connect, path


def test_idle_worker_passes_without_any_mutation(idle):
    assert activation.assert_worker_idle({'dir_test'})['pid'] == 123


def test_legacy_false_idle_does_not_override_new_media_activity(idle):
    health, _, _ = idle
    health['media_jobs_active'] = {'director': 1}
    with pytest.raises(RuntimeError, match='complete media'):
        activation.assert_worker_idle(set())


def test_active_persisted_tts_prevents_restart(idle):
    _, connect, path = idle
    with connect(path) as db:
        db.execute("insert into tts_jobs values ('processing')")
    with pytest.raises(RuntimeError, match='tts_jobs'):
        activation.assert_worker_idle(set())


def test_active_director_prevents_restart(idle, monkeypatch):
    original = activation.request
    monkeypatch.setattr(activation, 'request', lambda port, path, **kw:
                        {'status': 'processing'} if '/director-jobs/' in path else original(port, path, **kw))
    with pytest.raises(RuntimeError, match='Director task'):
        activation.assert_worker_idle({'dir_test'})
