import sqlite3
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from recording_resolution import RecordingResolution


def fixture(tmp_path, prober=lambda p: (720, 1280)):
    storage=tmp_path/'media';storage.mkdir()
    db=tmp_path/'db'
    with sqlite3.connect(db) as c:
        c.execute('CREATE TABLE recordings(id INTEGER PRIMARY KEY,filename,end_time,group_id,clip_filename,local_deleted,clipped,transcribed,skip_reason)')
        c.execute('CREATE TABLE recording_clips(id INTEGER PRIMARY KEY,recording_id)')
        for i in (1,2):
            (storage/f'{i}.mp4').write_bytes(b'original'+bytes([i]))
            c.execute('INSERT INTO recordings VALUES(?,?,?,NULL,NULL,0,-1,2,NULL)',(i,f'{i}.mp4','2020-01-01'))
    return RecordingResolution(db,storage,prober)


def test_roundtrip_and_duplicate_ids(tmp_path):
    lib=fixture(tmp_path)
    with lib.connect() as c: before=list(c.iterdump())
    plan=lib.inspect([1,1]);assert plan['count']==1
    batch=lib.execute_low([1],plan['fingerprint'])
    assert not (lib.storage/'1.mp4').exists()
    with lib.connect() as c: assert c.execute('SELECT local_deleted,clipped,transcribed FROM recordings WHERE id=1').fetchone()[:]==(1,-2,-2)
    lib.restore_low(batch['batch_id'])
    assert (lib.storage/'1.mp4').read_bytes()==b'original\x01'
    with lib.connect() as c: assert list(c.iterdump())==before


def test_keep_hd_failed_probe_and_linked(tmp_path):
    lib=fixture(tmp_path,lambda p:(1080,1920))
    assert lib.inspect([1])['count']==0
    def fail(p): raise OSError('probe failure')
    lib.prober=fail
    assert lib.inspect([1])['recordings'][0]['action']=='review'
    with lib.connect() as c:c.execute('UPDATE recordings SET group_id=3 WHERE id=1')
    lib.prober=lambda p:(720,1280)
    assert lib.inspect([1])['recordings'][0]['reason']=='linked_material'


def test_stale_preview_and_restore_collision(tmp_path):
    lib=fixture(tmp_path);plan=lib.inspect([1])
    (lib.storage/'1.mp4').write_bytes(b'changed')
    with pytest.raises(ValueError):lib.execute_low([1],plan['fingerprint'])
    plan=lib.inspect([1]);b=lib.execute_low([1],plan['fingerprint'])
    (lib.storage/'1.mp4').write_bytes(b'other')
    with pytest.raises(ValueError):lib.restore_low(b['batch_id'])
    assert (lib.storage/'1.mp4').read_bytes()==b'other'


def test_interrupted_move_before_database_commit(tmp_path):
    import json
    lib=fixture(tmp_path);plan=lib.inspect([1]);b=lib.execute_low([1],plan['fingerprint'])
    jp=lib.quarantine/b['batch_id']/'journal.json'
    j=json.loads(jp.read_text());j['state']='prepared';lib.journal(jp,j)
    with lib.connect() as c:c.execute('UPDATE recordings SET local_deleted=0,clipped=-1,transcribed=2,skip_reason=NULL WHERE id=1')
    lib.restore_low(b['batch_id'])
    assert (lib.storage/'1.mp4').exists()


def test_active_and_shared_sources_never_move(tmp_path):
    lib=fixture(tmp_path)
    with lib.connect() as c:c.execute('UPDATE recordings SET transcribed=1 WHERE id=1')
    assert lib.inspect([1])['count']==0
    with lib.connect() as c:
        c.execute('UPDATE recordings SET transcribed=2 WHERE id=1')
        c.execute("UPDATE recordings SET filename='1.mp4' WHERE id=2")
    assert lib.inspect([1])['count']==0


def test_queued_processing_is_protected(tmp_path):
    lib=fixture(tmp_path)
    with lib.connect() as c:c.execute('UPDATE recordings SET clipped=0 WHERE id=1')
    assert lib.inspect([1])['count']==0


def test_nested_source_uses_existing_media_resolver(tmp_path):
    lib=fixture(tmp_path)
    nested=lib.storage/'1';nested.mkdir()
    (lib.storage/'1.mp4').rename(nested/'1.mp4')
    lib.resolver=lambda name:nested/name
    plan=lib.inspect([1]);assert plan['count']==1
    batch=lib.execute_low([1],plan['fingerprint'])
    lib.restore_low(batch['batch_id'])
    assert (nested/'1.mp4').exists()


def test_connections_close_on_context_exit(tmp_path):
    lib=fixture(tmp_path)
    with lib.connect() as c:assert c.execute('SELECT 1').fetchone()[0]==1
    with pytest.raises(sqlite3.ProgrammingError):c.execute('SELECT 1')
