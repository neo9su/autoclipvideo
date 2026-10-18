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
