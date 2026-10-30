"""Exercise the finished-video route with real CPU media and a throwaway database."""
from contextlib import closing
from pathlib import Path
import hashlib,json,sqlite3,subprocess,tempfile,sys
from fastapi import FastAPI
from fastapi.testclient import TestClient
from publish_uploads import create_router


def run():
    with tempfile.TemporaryDirectory(prefix='manual-upload-test-') as directory:
        root=Path(directory);db=root/'test.db';folder=root/'media';source=root/'原样成片.mp4'
        with closing(sqlite3.connect(db)) as c, c:
            c.executescript('''CREATE TABLE rooms(id INTEGER PRIMARY KEY,name TEXT,url TEXT UNIQUE,enabled INTEGER);
            CREATE TABLE clip_groups(id INTEGER PRIMARY KEY,room_id INTEGER,label TEXT,is_custom INTEGER,editing_mode TEXT,publish_versions TEXT,merge_status INTEGER,classic_status INTEGER,merged_filename TEXT,enabled INTEGER DEFAULT 1);
            CREATE TABLE recordings(id INTEGER);CREATE TABLE publish_tasks(id INTEGER);''')
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=720x1280:r=25','-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t','16','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac',str(source)],check=True,capture_output=True,timeout=60,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        original=source.read_bytes();app=FastAPI();app.include_router(create_router(db,folder))
        with TestClient(app) as client:
            first=client.post('/api/publish-videos/upload',files={'file':(source.name,original,'video/mp4')})
            assert first.status_code==201,first.text
            receipt=first.json();group=receipt['group']
            assert group['label']=='原样成片' and group['classic_status']==2 and group['enabled']==0
            assert Path(group['merged_filename']).read_bytes()==original
            assert receipt['sha256']==hashlib.sha256(original).hexdigest()
            assert 15<=receipt['video']['duration']<=300
            retry=client.post('/api/publish-videos/upload',files={'file':('重复.mp4',original,'video/mp4')})
            assert retry.status_code==201 and retry.json()['reused'] and retry.json()['group']['id']==group['id']
            for name,data in [('broken.mp4',b'not-video'),('empty.mp4',b''),('x.exe',b'abc')]:
                result=client.post('/api/publish-videos/upload',files={'file':(name,data)})
                assert result.status_code==422,result.text
        small=FastAPI();small.include_router(create_router(db,folder,max_bytes=10))
        with TestClient(small) as client:
            assert client.post('/api/publish-videos/upload',files={'file':('big.mp4',b'x'*11)}).status_code==413
        assert not list(folder.glob('.*.upload*'))
        with closing(sqlite3.connect(db)) as c, c:
            assert c.execute('select count(*) from clip_groups').fetchone()[0]==1
            assert c.execute('select count(*) from recordings').fetchone()[0]==0
            assert c.execute('select count(*) from publish_tasks').fetchone()[0]==0
        return dict(real_video_http_upload=True,byte_identity=True,retry_dedup=True,invalid_empty_extension_size_rejected=True,partial_cleanup=True,no_recording_or_publish_jobs=True,duration=receipt['video']['duration'])


if __name__=='__main__':print(json.dumps(run()))
