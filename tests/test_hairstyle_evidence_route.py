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
