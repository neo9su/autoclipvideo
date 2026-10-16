import asyncio
import json
from pathlib import Path
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from wig_identity_review import hold_for_review, release_after_recheck, REVIEW_REQUIRED


class Cursor:
    def __init__(self, cur): self.cur = cur
    async def __aenter__(self): return self
    async def __aexit__(self, *args): self.cur.close()
    async def fetchone(self): return self.cur.fetchone()
    def __await__(self):
        async def ready(): return self
        return ready().__await__()
    @property
    def rowcount(self): return self.cur.rowcount


class Database:
    def __init__(self, db): self.db = db
    def execute(self, sql, args=()): return Cursor(self.db.execute(sql, args))
    async def commit(self): self.db.commit()
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass


@pytest.fixture
def connection():
    with sqlite3.connect(":memory:", check_same_thread=False) as db:
        db.execute("""CREATE TABLE clip_groups (id PRIMARY KEY,
          qianchuan_status, qianchuan_error, qianchuan_review,
          qianchuan_v2_status, qianchuan_v2_error, qianchuan_v2_review)""")
        db.execute("INSERT INTO clip_groups VALUES (7,0,'old-error','old-review',0,NULL,NULL)")
        db.commit()
        yield db


BAD = {"ok": False, "issues": [{"code": "recording_identity_conflict", "recording_id": 3}]}
GOOD = {"ok": True, "visual_verified": False}


def test_conflict_persists_as_review_and_keeps_original_state(connection):
    assert asyncio.run(hold_for_review(Database(connection), 7, BAD))
    row = connection.execute('SELECT qianchuan_status,qianchuan_review FROM clip_groups').fetchone()
    assert row[0] == REVIEW_REQUIRED
    saved = json.loads(row[1])
    assert saved['previous_state'] == {'status': 0, 'error': 'old-error', 'review': 'old-review'}
    assert saved['identity'] == BAD
    # Repeated check updates evidence without nesting history snapshots.
    asyncio.run(hold_for_review(Database(connection), 7, BAD))
    again = json.loads(connection.execute('SELECT qianchuan_review FROM clip_groups').fetchone()[0])
    assert again['previous_state'] == saved['previous_state']


def test_consistent_evidence_does_not_mutate_state(connection):
    before = list(connection.iterdump())
    assert not asyncio.run(hold_for_review(Database(connection), 7, GOOD))
    assert list(connection.iterdump()) == before


def test_recheck_cannot_override_conflicting_evidence(connection):
    asyncio.run(hold_for_review(Database(connection), 7, BAD))
    with pytest.raises(ValueError):
        asyncio.run(release_after_recheck(Database(connection), 7, BAD))
    assert connection.execute('SELECT qianchuan_status FROM clip_groups').fetchone()[0] == -5


@pytest.mark.parametrize('old_status,next_status', [(0,0),(1,0),(2,2),(-1,0)])
def test_only_repaired_evidence_releases_hold(connection, old_status, next_status):
    connection.execute('UPDATE clip_groups SET qianchuan_status=?', (old_status,))
    asyncio.run(hold_for_review(Database(connection), 7, BAD))
    assert asyncio.run(release_after_recheck(Database(connection), 7, GOOD)) == next_status
    row = connection.execute('SELECT qianchuan_status,qianchuan_error FROM clip_groups').fetchone()
    assert row == (next_status, None)


def test_v2_review_is_isolated_from_v1(connection):
    asyncio.run(hold_for_review(Database(connection), 7, BAD, 'qianchuan_v2'))
    assert connection.execute('SELECT qianchuan_status,qianchuan_v2_status FROM clip_groups').fetchone() == (0,-5)


def test_unknown_version_cannot_be_used_as_sql(connection):
    with pytest.raises(ValueError):
        asyncio.run(hold_for_review(Database(connection), 7, BAD, 'bad; DROP TABLE clip_groups'))


def test_review_state_is_excluded_from_real_claim_sql(connection):
    from pipeline_state import claim_pipeline_start
    for status in (-5, 2, 1):
        connection.execute('UPDATE clip_groups SET qianchuan_status=?', (status,))
        assert not asyncio.run(claim_pipeline_start(Database(connection), 'qianchuan_status', 7))
        assert not asyncio.run(claim_pipeline_start(Database(connection), 'qianchuan_status', 7, allow_missing_media_retry=True))


def test_recheck_does_not_touch_unrelated_failed_group(connection):
    connection.execute('INSERT INTO clip_groups VALUES (8,-2,NULL,NULL,0,NULL,NULL)')
    asyncio.run(hold_for_review(Database(connection), 7, BAD))
    asyncio.run(release_after_recheck(Database(connection), 7, GOOD))
    assert connection.execute('SELECT qianchuan_status FROM clip_groups WHERE id=8').fetchone()[0] == -2


@pytest.mark.parametrize('function', ['_run_qianchuan_pipeline', '_qianchuan_generate_bg'])
def test_actual_pipeline_returns_before_script_or_tts_on_conflict(connection, monkeypatch, function):
    import ast
    import logging
    import types
    from typing import Dict
    from unittest.mock import Mock, AsyncMock
    source = (Path(__file__).resolve().parents[1] / 'backend/api_v2.py').read_text()
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.AsyncFunctionDef) and n.name == function)
    database = Database(connection)
    monkeypatch.setitem(sys.modules, 'aiosqlite', types.SimpleNamespace(connect=lambda *a: database, Row=sqlite3.Row))
    monkeypatch.setitem(sys.modules, 'db', types.SimpleNamespace(aio_connect=lambda *a: database, DB_PATH='unused'))
    context = {'group': {'id': 7}, 'identity': BAD}
    script = Mock(side_effect=AssertionError('script must not run'))
    voice = AsyncMock(side_effect=AssertionError('TTS must not run'))
    ns = dict(Dict=Dict, logger=logging.getLogger('test'), hold_for_review=hold_for_review,
              score_product_match=Mock(return_value={'ok': False, 'identity': BAD}),
              load_group_context=AsyncMock(return_value=context), generate_qianchuan_script=script,
              voice_director=types.SimpleNamespace(generate_voiceover=voice), _COMPOSE_SEM=asyncio.Semaphore(1))
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'real-pipeline', 'exec'), ns)
    args = (7,) if function == '_run_qianchuan_pipeline' else (7, {})
    asyncio.run(ns[function](*args))
    assert connection.execute('SELECT qianchuan_status FROM clip_groups WHERE id=7').fetchone()[0] == -5
    script.assert_not_called()
    voice.assert_not_called()


def test_http_review_readonly_and_recheck_never_approves_conflict(connection, monkeypatch):
    import types
    from unittest.mock import AsyncMock
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from wig_identity_routes import identity_router
    db = Database(connection)
    loader = AsyncMock(return_value={'group': {'id': 7, 'qianchuan_status': -5}, 'identity': BAD})
    monkeypatch.setitem(sys.modules, 'db', types.SimpleNamespace(DB_PATH='unused', aio_connect=lambda: db))
    monkeypatch.setitem(sys.modules, 'qianchuan_matcher', types.SimpleNamespace(load_group_context=loader))
    app = FastAPI()
    app.include_router(identity_router, prefix='/api/v2/qianchuan')
    client = TestClient(app)
    before = list(connection.iterdump())
    response = client.get('/api/v2/qianchuan/group/7/identity-review')
    assert response.status_code == 200 and response.json()['read_only']
    assert list(connection.iterdump()) == before
    response = client.post('/api/v2/qianchuan/group/7/identity-recheck')
    assert response.status_code == 200 and not response.json()['success']
    assert response.json()['status'] == -5
    loader.return_value['identity'] = GOOD
    response = client.post('/api/v2/qianchuan/group/7/identity-recheck')
    assert response.json()['status'] == 0 and response.json()['success']
    assert not response.json()['visual_verified']
