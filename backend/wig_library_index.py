"""Independent, reversible metadata index. Registration never copies media."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import socket
import sqlite3
import subprocess


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def video_info(path):
    r = subprocess.run(['ffprobe','-v','error','-select_streams','v:0',
        '-show_entries','stream=width,height,codec_name:format=duration','-of','json',str(path)],
        capture_output=True,text=True,timeout=20,check=True)
    data = json.loads(r.stdout)
    stream = data['streams'][0]
    duration = float(data['format']['duration'])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('无法确认录像时长')
    return {**stream, 'duration_seconds': duration}


class WigLibraryIndex:
    def __init__(self, database):
        self.database = Path(database)

    @contextmanager
    def connect(self):
        self.database.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.database, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            con.executescript('''
                CREATE TABLE IF NOT EXISTS assets(asset_id TEXT PRIMARY KEY,sha256 TEXT NOT NULL,
                  size_bytes INTEGER NOT NULL,metadata TEXT NOT NULL,created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS locations(asset_id TEXT NOT NULL,host TEXT NOT NULL,path TEXT NOT NULL,
                  filename TEXT NOT NULL,recording_id INTEGER NOT NULL,room_id INTEGER,verified_at TEXT NOT NULL,
                  PRIMARY KEY(asset_id,host,path,recording_id));
                CREATE TABLE IF NOT EXISTS plans(plan_id TEXT PRIMARY KEY,asset_id TEXT NOT NULL,
                  recording_id INTEGER NOT NULL,document TEXT NOT NULL,state TEXT NOT NULL,created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,plan_id TEXT NOT NULL,
                  action TEXT NOT NULL,created_at TEXT NOT NULL);
            ''')
            with con:
                yield con
        finally:
            con.close()

    def register(self, source, recording_id, room_id, prober=None):
        source = Path(source).resolve(strict=True)
        before = source.stat()
        metadata = (prober or video_info)(source)
        digest = hashlib.sha256()
        with source.open('rb') as f:
            while block := f.read(4*1024*1024):
                digest.update(block)
        after = source.stat()
        if (before.st_size,before.st_mtime_ns,before.st_ino) != (after.st_size,after.st_mtime_ns,after.st_ino):
            raise ValueError('原录像正在变化，登记已取消')
        sha = digest.hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as con:
            con.execute('INSERT OR IGNORE INTO assets VALUES(?,?,?,?,?)',
                        (sha,sha,after.st_size,encoded(metadata),now))
            con.execute('INSERT INTO locations VALUES(?,?,?,?,?,?,?) ON CONFLICT(asset_id,host,path,recording_id) DO UPDATE SET verified_at=excluded.verified_at',
                        (sha,socket.gethostname(),str(source),source.name,recording_id,room_id,now))
        return {'asset_id':sha,'sha256':sha,'size_bytes':after.st_size,'metadata':metadata,
                'source_path':str(source),'registered_at':now,'media_copied':False}

    def save_plan(self, asset, recording_id, plan, subtitle_sha256):
        document = {**plan, 'asset_id':asset['asset_id'], 'subtitle_sha256':subtitle_sha256,
                    'media_created':False, 'time_basis':'original_video_seconds'}
        segments = []
        for raw in document['segments']:
            item = dict(raw)
            start,end = item['start_sec'],item['end_sec']
            if not all(math.isfinite(x) for x in (start,end)) or start < 0 or end <= start or end > asset['metadata']['duration_seconds']:
                raise ValueError('分段时间超出原录像范围')
            # Location/name changes do not change content + source-time identity.
            item['segment_id'] = hashlib.sha256(f"{asset['asset_id']}:{start:.3f}:{end:.3f}".encode()).hexdigest()[:24]
            if raw.get('relative_output') and raw.get('segment_id'):
                item['relative_output'] = raw['relative_output'].replace(raw['segment_id'], item['segment_id'])
            segments.append(item)
        if not segments:
            raise ValueError('计划没有有效分段')
        document['segments'] = segments
        payload = encoded(document)
        plan_id = hashlib.sha256(payload.encode()).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as con:
            if not con.execute('SELECT 1 FROM assets WHERE asset_id=?',(asset['asset_id'],)).fetchone():
                raise ValueError('原录像尚未登记')
            cursor = con.execute('INSERT OR IGNORE INTO plans VALUES(?,?,?,?,?,?)',
                          (plan_id,asset['asset_id'],recording_id,payload,'active',now))
            if cursor.rowcount:
                con.execute('INSERT INTO events(plan_id,action,created_at) VALUES(?,?,?)',(plan_id,'saved',now))
            state = con.execute('SELECT state FROM plans WHERE plan_id=?',(plan_id,)).fetchone()[0]
        return {'plan_id':plan_id,'state':state,'document':document}

    def list_plans(self, recording_id=None):
        if not self.database.exists():
            return []
        with self.connect() as con:
            query='SELECT * FROM plans'
            args=()
            if recording_id is not None:
                query+=' WHERE recording_id=?';args=(recording_id,)
            rows=con.execute(query+' ORDER BY created_at DESC LIMIT 100',args).fetchall()
        return [{**dict(row),'document':json.loads(row['document'])} for row in rows]

    def set_state(self, plan_id, state):
        if state not in ('active','withdrawn') or len(plan_id)!=64 or any(c not in '0123456789abcdef' for c in plan_id):
            raise ValueError('无效计划或状态')
        with self.connect() as con:
            row=con.execute('SELECT state FROM plans WHERE plan_id=?',(plan_id,)).fetchone()
            if row is None:
                raise ValueError('计划不存在')
            if row['state']!=state:
                con.execute('UPDATE plans SET state=? WHERE plan_id=?',(state,plan_id))
                con.execute('INSERT INTO events(plan_id,action,created_at) VALUES(?,?,?)',
                            (plan_id,state,datetime.now(timezone.utc).isoformat()))
        return {'plan_id':plan_id,'state':state}
