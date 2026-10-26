"""Restore measured end metadata for audited, stable, inactive HD sources only."""
from pathlib import Path
import datetime,json,math,os,sqlite3,time,urllib.request
ROOT=Path(r'C:\Users\neo\douyin_backend')
AUDIT=ROOT/'codex_operations/pipeline-audit-20261025/unfinished-audit.json'

def measured_end(row,item):
    d=float(item.get('duration',0))
    if item.get('status')!='valid_stable_unfinished' or not math.isfinite(d) or not 28<=d<=2702:return None
    if min(item.get('width',0),item.get('height',0))<1080 or max(item.get('width',0),item.get('height',0))<1920:return None
    if row['end_time'] is not None or row['local_deleted'] or row['transcribed'] or row['synced'] or row['clipped']:return None
    return (datetime.datetime.fromisoformat(row['start_time'])+datetime.timedelta(seconds=d)).isoformat()

def main():
    audit=json.loads(AUDIT.read_text(encoding='utf8'));assert audit.get('finished'),'Audit still running'
    with urllib.request.urlopen('http://127.0.0.1:8899/api/monitor/status',timeout=15) as h:status=json.load(h)
    active={Path(s['current_segment']).name for s in status['room_status'].values() if s.get('current_segment')}
    candidates=[]
    db=sqlite3.connect(ROOT/'douyin.db',timeout=15);db.row_factory=sqlite3.Row
    try:
        for item in audit['items']:
            if item['status']!='valid_stable_unfinished' or item['filename'] in active:continue
            row=dict(db.execute('SELECT * FROM recordings WHERE id=?',(item['id'],)).fetchone())
            end=measured_end(row,item)
            if end is None:continue
            p=Path(item['path']);a=p.stat()
            if a.st_size!=item['bytes'] or time.time()-a.st_mtime<600:continue
            time.sleep(2);b=p.stat()
            if (a.st_size,a.st_mtime_ns)!=(b.st_size,b.st_mtime_ns):continue
            candidates.append((row,item,end))
        backup=ROOT/'codex_rollbacks'/('unfinished-metadata-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));backup.mkdir()
        changes=[{'before':row,'after':dict(end_time=end,size_bytes=item['bytes'],duration_seconds=item['duration'],duration_status='accepted',skip_reason=None)} for row,item,end in candidates]
        (backup/'changes.json').write_text(json.dumps(changes,ensure_ascii=False,indent=2),encoding='utf8')
        (backup/'rollback.py').write_text(ROLLBACK,encoding='utf8')
        db.execute('BEGIN IMMEDIATE')
        for row,item,end in candidates:
            current=dict(db.execute('SELECT * FROM recordings WHERE id=?',(row['id'],)).fetchone())
            assert current==row,'Recording changed; abort rather than overwrite progress'
            db.execute("UPDATE recordings SET end_time=?,size_bytes=?,duration_seconds=?,duration_status='accepted',skip_reason=NULL WHERE id=?",(end,item['bytes'],item['duration'],row['id']))
        db.commit();print(json.dumps({'recovered_ids':[r['id'] for r,i,e in candidates],'backup':str(backup),'files_changed':False}))
    finally:db.close()

ROLLBACK=r'''from pathlib import Path
import json,sqlite3
b=Path(__file__).parent;changes=json.loads((b/'changes.json').read_text(encoding='utf8'))
db=sqlite3.connect(b.parents[1]/'douyin.db');db.row_factory=sqlite3.Row
try:
 db.execute('BEGIN IMMEDIATE')
 for item in changes:
  before=item['before'];after=item['after'];current=dict(db.execute('SELECT * FROM recordings WHERE id=?',(before['id'],)).fetchone())
  expected=before|after
  assert current==expected,'Processing has advanced; refuse to roll back consumed work'
 for item in changes:
  row=item['before'];keys=list(item['after']);db.execute('UPDATE recordings SET '+','.join(k+'=?' for k in keys)+' WHERE id=?',[row[k] for k in keys]+[row['id']])
 db.commit();print('Metadata restored; source files unchanged')
finally:db.close()
'''
if __name__=='__main__':main()
