import asyncio
from contextlib import closing
import sqlite3
import sys
from pathlib import Path

import aiosqlite
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'backend'))
import publish_scheduler as scheduler


@pytest.mark.parametrize('mode', ['missing', 'valid', 'no_cart', 'other_platform'])
def test_scheduler_cart_resolution_before_browser(tmp_path, monkeypatch, mode):
    database = tmp_path / 'test.sqlite'
    with closing(sqlite3.connect(database)) as db:
        db.executescript('''CREATE TABLE publish_tasks(id INTEGER PRIMARY KEY,status TEXT,error_msg TEXT,published_at TEXT,retry_count INTEGER DEFAULT 0);
        INSERT INTO publish_tasks(id,status) VALUES(1,'pending');
        CREATE TABLE products(id INTEGER PRIMARY KEY,product_id TEXT,product_name TEXT,product_url TEXT);''')
        db.execute('INSERT INTO products VALUES(1,?,?,?)', ('dom_test', '同名商品', '' if mode == 'missing' else 'https://example.invalid/item'))
        db.commit()
    monkeypatch.setattr(scheduler, 'aio_connect', lambda: aiosqlite.connect(database))
    calls = []
    class Publisher:
        async def publish(self, context, path):
            calls.append(context)
            return 'test-only-result'
    def publisher(platform):
        assert mode != 'missing', 'Missing link must fail before browser creation'
        return Publisher()
    async def quality(path): return True, ''
    async def notify(message): pass
    async def unexpected_retry(seconds): raise AssertionError('Metadata failure must not auto retry')
    monkeypatch.setattr(scheduler, '_get_publisher', publisher)
    monkeypatch.setattr(scheduler, 'resolve_video_path', lambda *args: ('test.mp4', 'test'))
    monkeypatch.setattr(scheduler, 'check_video_quality', quality)
    monkeypatch.setattr(scheduler, 'notify', notify)
    monkeypatch.setattr(scheduler.asyncio, 'sleep', unexpected_retry)
    task = dict(id=1, platform='bilibili' if mode == 'other_platform' else 'douyin',
                product_id=1, title='测试标题', video_path='test.mp4', no_cart=int(mode == 'no_cart'))
    asyncio.run(scheduler._execute_task(task))
    with closing(sqlite3.connect(database)) as db:
        status, error, retry = db.execute('SELECT status,error_msg,retry_count FROM publish_tasks').fetchone()
    if mode == 'missing':
        assert status == 'failed' and '商品链接' in error and retry == 0 and calls == []
    else:
        assert status == 'done' and len(calls) == 1
        if mode == 'valid': assert calls[0]['_product_douyin_ids'] == ['https://example.invalid/item']
        else: assert '_product_douyin_ids' not in calls[0]
