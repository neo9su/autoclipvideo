"""Read-only interrupted recording audit; run as the desktop storage owner."""
from pathlib import Path
import concurrent.futures,datetime,json,math,os,sqlite3,subprocess,time,urllib.request
ROOT=Path(r'C:\Users\neo\douyin_backend')
OUTPUT=ROOT/'codex_operations/pipeline-audit-20261025/unfinished-audit.json'

def inspect(row,active):
    result=dict(row)
    if row['filename'] in active:return result|{'status':'active_preserved'}
    roots=[Path(r'F:\douyin_recordings'),ROOT/'recordings']
    try:
        path=next((p for root in roots for p in [root/row['filename'],root/str(row['room_id'])/row['filename']] if p.is_file()),None)
        if path is None:return result|{'status':'missing_or_inaccessible'}
        before=path.stat();result.update(path=str(path),bytes=before.st_size)
        if time.time()-before.st_mtime<600:return result|{'status':'recent_preserved'}
        probe=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type,width,height','-of','json',str(path)],capture_output=True,timeout=12,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if probe.returncode:return result|{'status':'invalid_container_preserved','detail':probe.stderr.decode(errors='replace')[-400:]}
        meta=json.loads(probe.stdout);duration=float(meta.get('format',{}).get('duration',0));video=next((s for s in meta.get('streams',[]) if s.get('codec_type')=='video'),None)
        time.sleep(2);after=path.stat()
        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):return result|{'status':'changing_preserved'}
        if not video or not math.isfinite(duration) or duration<=0:return result|{'status':'invalid_metadata_preserved'}
        return result|{'status':'valid_stable_unfinished','duration':duration,'width':video.get('width'),'height':video.get('height')}
    except subprocess.TimeoutExpired:return result|{'status':'probe_timeout_preserved'}
    except Exception as exc:return result|{'status':'inspection_error','detail':type(exc).__name__+': '+str(exc)[:200]}

def main():
    with urllib.request.urlopen('http://127.0.0.1:8899/api/monitor/status',timeout=15) as h:monitor=json.load(h)
    active={Path(s['current_segment']).name for s in monitor['room_status'].values() if s.get('current_segment')}
    with sqlite3.connect(ROOT/'douyin.db') as db:
        db.row_factory=sqlite3.Row;rows=[dict(r) for r in db.execute('SELECT id,room_id,filename,start_time FROM recordings WHERE end_time IS NULL AND local_deleted=0 ORDER BY id DESC')]
    state={'read_only':True,'started_at':datetime.datetime.now().isoformat(),'items':[]}
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures=[pool.submit(inspect,r,active) for r in rows]
        for f in concurrent.futures.as_completed(futures):
            state['items'].append(f.result());OUTPUT.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf8')
    state['finished']=True;OUTPUT.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf8')
if __name__=='__main__':main()
