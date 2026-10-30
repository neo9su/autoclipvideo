import ast
import asyncio
import sqlite3
import sys
from pathlib import Path
from typing import Optional
import aiosqlite
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'backend'))
import media_probe
from group_lifecycle import OPEN_GROUP_SQL

@pytest.mark.asyncio
async def test_completed_and_running_groups_are_preserved_and_new_draft_reused(tmp_path):
    path=tmp_path/'test.db'
    fields=['is_custom','merge_status','classic_status','director_status','creative_status','realistic_status','conservative_status','qianchuan_status']
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE clip_groups(id INTEGER PRIMARY KEY,room_id INTEGER,wig_model TEXT,wig_color TEXT,label TEXT,editing_mode TEXT,'+','.join(f'{n} INTEGER DEFAULT 0' for n in fields)+')')
        db.execute("INSERT INTO clip_groups(room_id,wig_model,wig_color,merge_status,classic_status) VALUES (1,'人生','黑',2,2)")
    source=(Path(__file__).parents[1]/'backend'/'analyzer.py').read_text()
    node=next(n for n in ast.parse(source).body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_get_or_create_group')
    ns={'Optional':Optional,'aiosqlite':aiosqlite,'aio_connect':lambda:aiosqlite.connect(path)}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'group-under-test','exec'),ns)
    fn=ns['_get_or_create_group']
    assert await fn(1,'人生','黑')==2
    assert await fn(1,'人生','黑')==2
    with sqlite3.connect(path) as db:db.execute('UPDATE clip_groups SET classic_status=1 WHERE id=2')
    assert await fn(1,'人生','黑')==3
    with sqlite3.connect(path) as db:assert db.execute('SELECT merge_status FROM clip_groups WHERE id=1').fetchone()[0]==2

class Probe:
    returncode=0
    killed=False
    reads=0
    async def communicate(self):self.reads+=1;return b'2700.5',b''
    def kill(self):self.killed=True

@pytest.mark.asyncio
async def test_valid_long_recording_metadata(monkeypatch):
    p=Probe()
    async def spawn(*a,**kw):return p
    monkeypatch.setattr(asyncio,'create_subprocess_exec',spawn)
    assert await media_probe.validate_mp4('source.mp4')==(True,'')

@pytest.mark.asyncio
async def test_timeout_is_retryable_and_child_is_reaped(monkeypatch):
    p=Probe()
    async def spawn(*a,**kw):return p
    async def timeout(coro,timeout):coro.close();raise asyncio.TimeoutError()
    monkeypatch.setattr(asyncio,'create_subprocess_exec',spawn);monkeypatch.setattr(asyncio,'wait_for',timeout)
    ok,error=await media_probe.validate_mp4('slow.mp4')
    assert not ok and error.startswith(media_probe.TRANSIENT_PROBE_PREFIX)
    assert p.killed and p.reads==1

@pytest.mark.asyncio
async def test_real_container_error_stays_invalid(monkeypatch):
    p=Probe();p.returncode=1
    async def read():return b'',b'moov atom not found'
    p.communicate=read
    async def spawn(*a,**kw):return p
    monkeypatch.setattr(asyncio,'create_subprocess_exec',spawn)
    ok,error=await media_probe.validate_mp4('bad.mp4')
    assert not ok and error.startswith('invalid mp4:')
