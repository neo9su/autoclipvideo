import ast
import asyncio
import heapq
import logging
import os
from pathlib import Path
import sqlite3
from typing import Optional

import aiosqlite
import pytest

ROOT=Path(__file__).parents[1]


def load(path,names,env):
    tree=ast.parse((ROOT/path).read_text())
    nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in names]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),env)
    return env


@pytest.mark.asyncio
async def test_admission_blocks_overlapping_requests_but_allows_future_runs():
    lock=asyncio.Lock();entered=asyncio.Event();release=asyncio.Event();calls=[]
    pending={};running=set()
    async def enqueue(rid,*args,**kwargs):
        calls.append(rid);entered.set();await release.wait();pending[rid]={};return 'accepted'
    env=load('backend/transcribe.py',{'_run_editor'},dict(Optional=Optional,_dispatch_lk=lambda:lock,
        _pending_meta=pending,_running_ids=running,_enqueuing_ids=set(),_enqueue_editor=enqueue,logger=logging.getLogger('test')))
    first=asyncio.create_task(env['_run_editor'](1,'source','subs'))
    await entered.wait()
    assert await env['_run_editor'](1,'source','subs') is None  # validation still running
    release.set();assert await first=='accepted'
    await env['_run_editor'](1,'source','subs')  # queued
    pending.clear();running.add(1)
    await env['_run_editor'](1,'source','subs')  # running
    assert calls==[1]
    running.clear();assert await env['_run_editor'](1,'source','subs')=='accepted'
    assert calls==[1,1]


@pytest.mark.asyncio
async def test_validation_failure_releases_admission():
    lock=asyncio.Lock();calls=[]
    async def fail(*args,**kwargs):raise ValueError('invalid source')
    env=load('backend/transcribe.py',{'_run_editor'},dict(Optional=Optional,_dispatch_lk=lambda:lock,
        _pending_meta={},_running_ids=set(),_enqueuing_ids=set(),_enqueue_editor=fail,logger=logging.getLogger('test')))
    with pytest.raises(ValueError):await env['_run_editor'](1,'source','subs')
    assert env['_enqueuing_ids']==set()
    async def succeed(*args,**kwargs):calls.append(1)
    env['_enqueue_editor']=succeed
    await env['_run_editor'](1,'source','subs')
    assert calls==[1]


@pytest.mark.asyncio
async def test_dispatch_never_starts_same_recording_twice():
    started=[];lock=asyncio.Lock()
    async def run(rid,meta):started.append(rid)
    env=load('backend/transcribe.py',{'_try_dispatch'},dict(asyncio=asyncio,heapq=heapq,_dispatch_lk=lambda:lock,
        _pending_heap=[[50,1,1],[50,2,2]],_pending_meta={1:{},2:{}},_running_ids={1},_paused_ids=set(),
        MAX_CONCURRENT_CLIPS=3,_memory_pressure=False,_run_job_from_queue=run))
    await env['_try_dispatch']();await asyncio.sleep(0)
    assert started==[2] and 1 in env['_pending_meta'] and env['_running_ids']=={1,2}


@pytest.mark.asyncio
async def test_startup_preserves_real_clips_in_either_storage_root(tmp_path):
    current=tmp_path/'current';legacy=tmp_path/'project/recordings'
    current.mkdir();legacy.mkdir(parents=True);(tmp_path/'project/backend').mkdir()
    for root,name in [(current,'ok.mp4'),(legacy,'legacy.mp4'),(legacy,'source.mp4'),(current,'source_current.mp4')]:
        (root/name).write_bytes(b'fixture')
    db_path=tmp_path/'db.sqlite'
    rows=[(1,'source.mp4','ok.mp4',2,0),(2,'source.mp4','legacy.mp4',2,0),
          (3,'source_current.mp4','missing.mp4',2,0),(4,'absent_source.mp4','missing.mp4',2,0),
          (5,'source_current.mp4','missing.mp4',2,1),(6,'source.mp4','ok.mp4',1,0),(7,'source.mp4',None,1,0)]
    with sqlite3.connect(db_path) as db:
        db.execute('create table recordings(id,filename,clip_filename,clipped,local_deleted)')
        db.executemany('insert into recordings values (?,?,?,?,?)',rows)
        db.execute('create table clip_groups(merge_status,merged_filename,director_final_video,director_status,creative_status,qianchuan_status,realistic_status,conservative_status)')
    env=load('backend/main.py',{'_recording_file_path','_recording_file_exists','_reset_stuck_clip_tasks'},dict(
        os=os,__file__=str(tmp_path/'project/backend/main.py'),RECORDINGS_DIR=str(current),aiosqlite=aiosqlite,
        aio_connect=lambda:aiosqlite.connect(db_path),logger=logging.getLogger('test')))
    await env['_reset_stuck_clip_tasks']()
    with sqlite3.connect(db_path) as db:
        statuses=dict(db.execute('select id,clipped from recordings'))
        assert statuses=={1:2,2:2,3:0,4:2,5:2,6:2,7:0}
        assert db.execute('select clip_filename from recordings where id=3').fetchone()[0] is None
    assert (current/'ok.mp4').exists() and (legacy/'legacy.mp4').exists()
