import sys
from pathlib import Path
from datetime import datetime, timezone
import os
import sqlite3
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'backend'))
from history_library import HistoryLibrary, three_months_before


def test_calendar_month_cutoff():
    assert three_months_before(datetime(2026,5,31,tzinfo=timezone.utc)).isoformat().startswith('2026-02-28')


def test_cleanup_restore_and_preserve_source(tmp_path):
    db=tmp_path/'db.sqlite';storage=tmp_path/'media';storage.mkdir()
    source=storage/'original.mp4';source.write_bytes(b'original')
    clip=storage/'old.mp4';clip.write_bytes(b'old generated')
    os.utime(clip,(1,1))
    with sqlite3.connect(db) as c:
        c.execute('CREATE TABLE clip_groups(id INTEGER PRIMARY KEY,created_at,label,qianchuan_status,qianchuan_final_video)')
        c.execute('CREATE TABLE recordings(id INTEGER PRIMARY KEY,group_id,filename,clip_filename,clipped,transcribed,end_time)')
        c.execute('CREATE TABLE recording_clips(id INTEGER PRIMARY KEY,recording_id,clip_filename)')
        c.execute('CREATE TABLE publish_tasks(id INTEGER PRIMARY KEY,group_id,status,video_path,manual_published)')
        c.execute('INSERT INTO clip_groups VALUES(1,?,?,2,?)',('2020-01-01','old',str(clip)))
        c.execute('INSERT INTO recordings VALUES(1,1,?,?,2,2,?)',(str(source),str(clip),'2020-01-01'))
        c.execute('INSERT INTO recording_clips VALUES(1,1,?)',(str(clip),))
        c.execute('INSERT INTO publish_tasks VALUES(1,1,?,?,0)',('done',str(clip)))
        c.commit();before=list(c.iterdump())
    library=HistoryLibrary(db,storage)
    assert not library.preview('unpublished')['groups']
    plan=library.preview('published')
    assert len(plan['groups'])==1
    result=library.execute('published',plan['cutoff'],plan['fingerprint'])
    assert source.exists() and not clip.exists()
    with sqlite3.connect(db) as c:assert c.execute('SELECT COUNT(*) FROM clip_groups').fetchone()[0]==0
    library.restore(result['batch_id'])
    assert clip.read_bytes()==b'old generated'
    with sqlite3.connect(db) as c:assert list(c.iterdump())==before


def inventory(tmp_path, task_status='done', shared=False, young=False):
    db=tmp_path/'db';storage=tmp_path/'files';storage.mkdir()
    source=storage/'source.mp4';source.write_bytes(b'source')
    clip=storage/'clip.mp4';clip.write_bytes(b'clip')
    if not young:os.utime(clip,(1,1))
    with sqlite3.connect(db) as c:
        c.execute('CREATE TABLE clip_groups(id INTEGER PRIMARY KEY,created_at,label,qianchuan_status,qianchuan_final_video)')
        c.execute('CREATE TABLE recordings(id INTEGER PRIMARY KEY,group_id,filename,clip_filename,clipped,transcribed,end_time)')
        c.execute('CREATE TABLE recording_clips(id INTEGER PRIMARY KEY,recording_id,clip_filename)')
        c.execute('CREATE TABLE publish_tasks(id INTEGER PRIMARY KEY,group_id,status,video_path,manual_published)')
        c.execute('INSERT INTO clip_groups VALUES(1,?,?,2,?)',('2020-01-01','old',str(clip)))
        c.execute('INSERT INTO recordings VALUES(1,1,?,?,2,2,?)',(str(source),str(clip),'2020-01-01'))
        c.execute('INSERT INTO publish_tasks VALUES(1,1,?,?,0)',(task_status,str(clip)))
        if shared:c.execute('INSERT INTO clip_groups VALUES(2,?,?,2,?)',('2099-01-01','new',str(clip)))
    return HistoryLibrary(db,storage),clip


def test_pending_publish_and_recent_output_are_preserved(tmp_path):
    a=tmp_path/'a';a.mkdir();library,_=inventory(a,task_status='scheduled')
    assert not library.preview()['groups']
    b=tmp_path/'b';b.mkdir();library,_=inventory(b,young=True)
    assert not library.preview()['groups']


def test_shared_output_not_moved(tmp_path):
    library,clip=inventory(tmp_path,shared=True)
    plan=library.preview();assert len(plan['groups'])==1
    assert not plan['groups'][0]['files']
    result=library.execute('all',plan['cutoff'],plan['fingerprint'])
    assert clip.exists()
    library.restore(result['batch_id']);assert clip.exists()


def test_stale_preview_rejected_before_file_move(tmp_path):
    import pytest
    library,clip=inventory(tmp_path);plan=library.preview()
    with library.connect() as c:c.execute("UPDATE publish_tasks SET status='scheduled' WHERE id=1")
    with pytest.raises(ValueError):library.execute('all',plan['cutoff'],plan['fingerprint'])
    assert clip.exists()


def test_unreadable_media_excludes_group_instead_of_deleting_its_record(tmp_path, monkeypatch):
    library, clip=inventory(tmp_path)
    original=Path.is_symlink
    def inaccessible(path):
        if path==clip:raise PermissionError('offline or restricted archive')
        return original(path)
    monkeypatch.setattr(Path,'is_symlink',inaccessible)
    assert not library.preview()['groups']
    assert clip.exists()
