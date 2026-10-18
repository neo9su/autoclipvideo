import asyncio
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import types

import aiosqlite
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'backend'))
import publish_scheduler as scheduler


@pytest.mark.parametrize('mode', ['schemes', 'legacy', 'fallback', 'existing', 'generation_error'])
def test_resolved_metadata_reaches_publisher(tmp_path, monkeypatch, mode):
    database = tmp_path / 'metadata.sqlite'
    with closing(sqlite3.connect(database)) as db:
        db.executescript('''CREATE TABLE publish_tasks(id INTEGER PRIMARY KEY,status TEXT,error_msg TEXT,published_at TEXT,retry_count INTEGER DEFAULT 0,group_id INTEGER,platform TEXT,title TEXT,description TEXT,tags TEXT);
        INSERT INTO publish_tasks(id,status,group_id,platform) VALUES(1,'pending',7,'douyin');
        CREATE TABLE clip_groups(id INTEGER PRIMARY KEY,merged_filename TEXT,qianchuan_final_video TEXT,realistic_final_video TEXT,conservative_final_video TEXT,creative_final_video TEXT,director_final_video TEXT);
        INSERT INTO clip_groups(id) VALUES(7);''')
    task = dict(id=1, platform='douyin', group_id=7, no_cart=1, retry_count=2,
                video_path='test.mp4', title='用户标题' if mode == 'existing' else None,
                description='用户描述', tags='用户话题')
    generated = dict(title='生成标题', description='生成描述', tags='发型,假发')
    calls, notifications, generations = [], [], []
    async def generate(group_id):
        generations.append(group_id)
        if mode == 'generation_error': raise RuntimeError('fixture generation failure')
        if mode == 'fallback': return None
        return {'schemes': [generated]} if mode == 'schemes' else generated
    monkeypatch.setitem(sys.modules, 'meta_generator', types.SimpleNamespace(generate_meta=generate))
    monkeypatch.setattr(scheduler, 'aio_connect', lambda: aiosqlite.connect(database))
    class Publisher:
        async def publish(self, context, path):
            calls.append(context)
            return 'test-only-result'
    async def quality(path): return True, ''
    async def notify(message): notifications.append(message)
    monkeypatch.setattr(scheduler, '_get_publisher', lambda platform: Publisher())
    monkeypatch.setattr(scheduler, 'resolve_video_path', lambda *args: ('test.mp4','fixture'))
    monkeypatch.setattr(scheduler, 'check_video_quality', quality)
    monkeypatch.setattr(scheduler, 'notify', notify)
    asyncio.run(scheduler._execute_task(task))
    with closing(sqlite3.connect(database)) as db:
        row = db.execute('SELECT status,title,description,tags FROM publish_tasks WHERE id=1').fetchone()
    if mode == 'generation_error':
        assert calls == [] and row[0] == 'failed'
        return
    expected = (('用户标题','用户描述','用户话题') if mode == 'existing' else
                ('分组 7','','') if mode == 'fallback' else ('生成标题','生成描述','发型,假发'))
    assert row[0] == 'done' and len(calls) == 1
    assert tuple(calls[0][key] for key in ('title','description','tags')) == expected
    assert task['description'] == '用户描述', 'Input task should not be mutated'
    if mode == 'existing': assert generations == []
    else: assert row[1:] == expected
    assert any(expected[0] in message for message in notifications)
