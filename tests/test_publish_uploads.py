import hashlib,json,sqlite3,sys,subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'backend'))
from publish_uploads import commit_video,probe_video,create_router


def database(tmp_path):
    db=tmp_path/'test.db'
    with sqlite3.connect(db) as c:
        c.executescript('''CREATE TABLE rooms(id INTEGER PRIMARY KEY,name TEXT,url TEXT UNIQUE,enabled INTEGER);
        CREATE TABLE clip_groups(id INTEGER PRIMARY KEY,room_id INTEGER,label TEXT,is_custom INTEGER,editing_mode TEXT,publish_versions TEXT,merge_status INTEGER,classic_status INTEGER,merged_filename TEXT,enabled INTEGER DEFAULT 1);
        CREATE TABLE recordings(id INTEGER);CREATE TABLE publish_tasks(id INTEGER);''')
    return db


def test_same_bytes_retry_and_parallel_upload_share_one_group(tmp_path):
    db=database(tmp_path);folder=tmp_path/'media';folder.mkdir();data=b'video';sha=hashlib.sha256(data).hexdigest()
    def upload(n):
        part=folder/f'{n}.part';part.write_bytes(data)
        return commit_video(db,folder,part,sha,'我的视频','.mp4')
    with ThreadPoolExecutor(max_workers=2) as pool:a,b=pool.map(upload,[1,2])
    assert a['group']['id']==b['group']['id']
    assert a['reused'] != b['reused']
    assert Path(a['group']['merged_filename']).read_bytes()==data
    assert a['group']['enabled']==0 and a['group']['editing_mode']=='manual_upload'
    assert a['group']['classic_available'] and not a['auto_publish'] and not a['reprocess']
    with sqlite3.connect(db) as c:
        assert c.execute('select count(*) from clip_groups').fetchone()[0]==1
        assert c.execute('select count(*) from recordings').fetchone()[0]==0
        assert c.execute('select count(*) from publish_tasks').fetchone()[0]==0


def test_actual_probe_enforces_existing_publish_duration_and_container():
    good={'streams':[{'codec_type':'video','width':1080,'height':1920,'codec_name':'h264'}],'format':{'duration':'15','format_name':'mov,mp4,m4a,3gp,3g2,mj2'}}
    with patch('publish_uploads.subprocess.run',return_value=subprocess.CompletedProcess([],0,json.dumps(good).encode())):
        assert probe_video('video.mp4')['duration']==15
    for duration in ['14.9','300.1','nan']:
        good['format']['duration']=duration
        with patch('publish_uploads.subprocess.run',return_value=subprocess.CompletedProcess([],0,json.dumps(good).encode())):
            with pytest.raises(ValueError):probe_video('video.mp4')
    good['format'].update(duration='16',format_name='avi')
    with patch('publish_uploads.subprocess.run',return_value=subprocess.CompletedProcess([],0,json.dumps(good).encode())):
        with pytest.raises(ValueError,match='格式'):probe_video('video.mp4')


def test_upload_http_success_limits_failures_and_no_partial_groups(tmp_path):
    fastapi=pytest.importorskip('fastapi');pytest.importorskip('multipart')
    from fastapi.testclient import TestClient
    db=database(tmp_path);folder=tmp_path/'media'
    def probe(path):
        if path.read_bytes()==b'broken':raise ValueError('坏视频')
        return dict(duration=16,width=1080,height=1920)
    app=fastapi.FastAPI();app.include_router(create_router(db,folder,probe=probe,max_bytes=10))
    with TestClient(app) as client:
        for filename,body,status in [('x.exe',b'video',422),('x.mp4',b'',422),('x.mp4',b'broken',422),('x.mp4',b'x'*11,413)]:
            assert client.post('/api/publish-videos/upload',files={'file':(filename,body)}).status_code==status
        first=client.post('/api/publish-videos/upload',files={'file':('我的视频.mp4',b'video')})
        assert first.status_code==201,first.text
        assert first.json()['group']['label']=='我的视频'
        retry=client.post('/api/publish-videos/upload',files={'file':('again.mp4',b'video')})
        assert retry.status_code==201 and retry.json()['group']['id']==first.json()['group']['id']
    assert not list(folder.glob('.*.upload*'))
    with sqlite3.connect(db) as c:assert c.execute('select count(*) from clip_groups').fetchone()[0]==1
