"""Exercise the production root-sidecar layout through the read-only route."""
import asyncio
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import history_library_routes as routes
import media_contract
from history_library import HistoryLibrary


def test_route_uses_existing_root_sidecar_resolver(tmp_path,monkeypatch):
    db=tmp_path/'db';root=tmp_path/'media';(root/'1').mkdir(parents=True)
    source=root/'1'/'source.mp4';source.write_bytes(b'fixture')
    subtitle=root/'source.srt';subtitle.write_text('1\n00:00:06,000 --> 00:00:07,000\n这是人生\n',encoding='utf-8')
    c=sqlite3.connect(db)
    c.execute('CREATE TABLE recordings(id,filename,local_deleted,end_time,room_id)')
    c.execute("INSERT INTO recordings VALUES(8,'source.mp4',0,'2020-01-01',1)")
    c.execute('CREATE TABLE products(id,product_name,enabled,room_id)')
    c.execute("INSERT INTO products VALUES(1,'小圆-夺回&人生【仿递针】',1,1)")
    c.execute("INSERT INTO products VALUES(2,'小圆-夺回&人生【仿递针】',1,2)")
    c.commit();c.close()
    monkeypatch.setattr(routes,'service',lambda:HistoryLibrary(db,root))
    monkeypatch.setattr(media_contract,'resolve_media_file',lambda filename:source)
    called=[]
    def resolve(filename):called.append(filename);return subtitle
    monkeypatch.setattr(media_contract,'resolve_srt_file',resolve)
    result=asyncio.run(routes.hairstyle_evidence(8))
    assert called==['source.mp4']
    assert result['read_only'] and not result['visual_verified']
    assert result['mentions'][0]['catalogue_ids']==[1]
    assert result['mentions'][0]['current_assertion']
    assert source.read_bytes()==b'fixture'


def test_client_cannot_assert_visual_identity():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        routes.ArchiveBoundary(start_sec=0,end_sec=10,visual_verified=True)
    with pytest.raises(ValidationError):
        routes.ArchiveBoundary(start_sec=float('nan'),end_sec=10)


def test_save_plan_stays_pending_and_can_be_restored(tmp_path,monkeypatch):
    import wig_library_index
    source=tmp_path/'source.mp4';source.write_bytes(b'fixture')
    raw=b'1\n00:00:06,000 --> 00:00:07,000\n'+ '这是人生'.encode()+b'\n'
    monkeypatch.setattr(routes,'recording_context',lambda rid:({'room_id':1},[{'id':1,'product_name':'小圆-夺回&人生【仿递针】'}],source,raw))
    index=wig_library_index.WigLibraryIndex(tmp_path/'index.db')
    monkeypatch.setattr(routes,'library_index',lambda:index)
    monkeypatch.setattr(wig_library_index,'video_info',lambda p:{'duration_seconds':20,'width':1080,'height':1920})
    body=routes.ArchivePlanRequest(boundaries=[routes.ArchiveBoundary(start_sec=5,end_sec=10,wig='人生',current_evidence='这是人生')])
    result=asyncio.run(routes.save_archive_plan(8,body))
    segment=result['document']['segments'][0]
    assert segment['transcript_evidence']['verified']
    assert segment['status']=='needs_evidence' and result['document']['ready_count']==0
    assert result['document']['media_created'] is False
    asyncio.run(routes.change_archive_plan(result['plan_id'],'withdraw'))
    assert index.list_plans()[0]['state']=='withdrawn'
    asyncio.run(routes.change_archive_plan(result['plan_id'],'restore'))
    assert index.list_plans()[0]['state']=='active'
    assert source.read_bytes()==b'fixture'
