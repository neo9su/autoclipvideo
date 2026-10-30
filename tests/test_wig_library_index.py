import sqlite3
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from wig_library_index import WigLibraryIndex


def fixture(tmp_path):
    source=tmp_path/'source.mp4';source.write_bytes(b'original media fixture')
    index=WigLibraryIndex(tmp_path/'index'/'library.db')
    asset=index.register(source,8,1,lambda p:{'duration_seconds':20,'width':1080,'height':1920})
    plan={'recording_id':8,'segments':[{'start_sec':1.,'end_sec':9.,'hairstyle_name':'人生','status':'needs_evidence'}]}
    return source,index,asset,plan


def test_content_identity_dedup_and_source_unchanged(tmp_path):
    source,index,asset,plan=fixture(tmp_path)
    copy=tmp_path/'other.mp4';copy.write_bytes(source.read_bytes())
    second=index.register(copy,9,1,lambda p:asset['metadata'])
    assert second['asset_id']==asset['asset_id'] and not second['media_copied']
    with index.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM assets').fetchone()[0]==1
        assert c.execute('SELECT COUNT(*) FROM locations').fetchone()[0]==2
    assert source.read_bytes()==b'original media fixture'


def test_idempotent_plan_and_reversible_withdrawal(tmp_path):
    source,index,asset,plan=fixture(tmp_path)
    a=index.save_plan(asset,8,plan,'srt-sha')
    assert index.save_plan(asset,8,plan,'srt-sha')['plan_id']==a['plan_id']
    index.set_state(a['plan_id'],'withdrawn')
    assert index.save_plan(asset,8,plan,'srt-sha')['state']=='withdrawn'
    index.set_state(a['plan_id'],'active')
    assert len(index.list_plans(8))==1 and not index.list_plans(9)
    assert index.list_plans()[0]['state']=='active'
    with index.connect() as c:assert c.execute('SELECT COUNT(*) FROM events').fetchone()[0]==3


def test_changed_names_preserve_segment_identity_and_keep_versions(tmp_path):
    _,index,asset,plan=fixture(tmp_path)
    first=index.save_plan(asset,8,plan,'srt-sha')
    plan['segments'][0]['hairstyle_name']='夺回&人生'
    second=index.save_plan(asset,8,plan,'srt-sha')
    assert first['plan_id']!=second['plan_id']
    assert first['document']['segments'][0]['segment_id']==second['document']['segments'][0]['segment_id']
    assert len(index.list_plans())==2


def test_bad_time_and_changing_source_cannot_save(tmp_path):
    source,index,asset,plan=fixture(tmp_path)
    plan['segments'][0]['end_sec']=21
    with pytest.raises(ValueError):index.save_plan(asset,8,plan,'srt-sha')
    def mutate(p):p.write_bytes(b'changed');return asset['metadata']
    with pytest.raises(ValueError):index.register(source,8,1,mutate)
    assert index.list_plans()==[]
