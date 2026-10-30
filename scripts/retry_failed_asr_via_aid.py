"""Finite retry of transient ASR failures through AID only; retain original DB state."""
from pathlib import Path
import json,sqlite3,sys,traceback
ROOT=Path(r'C:\Users\neo\douyin_backend')
BATCH=ROOT/'codex_operations/failed-retry-20261025'
OLD=ROOT/'codex_operations/production-20261025'

def main():
    sys.path.insert(0,str(OLD))
    from aid_transcribe_recording import run,save
    BATCH.mkdir(exist_ok=True)
    # Stable idempotency keys are preserved by the existing scheduler client.
    (BATCH/'aid_gpu_client.py').write_bytes((OLD/'aid_gpu_client.py').read_bytes())
    with sqlite3.connect(ROOT/'douyin.db') as db:
        db.row_factory=sqlite3.Row
        rows=[dict(r) for r in db.execute("SELECT * FROM recordings WHERE transcribed=-1 AND local_deleted=0 AND end_time IS NOT NULL AND transcribe_error IN ('Timed out after 600s','invalid mp4: ffprobe timeout (>3s)') ORDER BY id DESC")]
    before=BATCH/'before-recordings.json'
    if not before.exists():save(before,rows)
    progress=BATCH/'retry-progress.json'
    state=json.loads(progress.read_text()) if progress.exists() else {'items':[],'business_db_changed':False,'source_files_changed':False}
    done={r['id'] for r in state['items']}
    for row in rows:
        if row['id'] in done:continue
        item={'id':row['id'],'previous_error':row['transcribe_error']}
        if (row.get('duration_seconds') or 0)>1800:
            item['status']='DEFERRED_REQUIRES_AUDIO_CHUNKING'
        else:
            state['active_id']=row['id'];save(progress,state)
            try:
                # Reuse prior evidence/job ID when a prerequisite attempt already exists.
                prior=OLD/f"recording-{row['id']}.json";current=BATCH/prior.name
                if prior.exists() and not current.exists():current.write_bytes(prior.read_bytes())
                run(row['id'],BATCH)
                result=json.loads(current.read_text())
                item.update(status=result['phase'],job_id=result.get('job_id'),transcript=result.get('transcript'),error=result.get('error'))
            except Exception as exc:
                p=BATCH/f"recording-{row['id']}.json"
                result=json.loads(p.read_text()) if p.exists() else {}
                item.update(status=result.get('phase','PREFLIGHT_ERROR'),job_id=result.get('job_id'),reason=str(exc)[:300])
        state['items'].append(item);state.pop('active_id',None);save(progress,state)
    state['finished']=True;save(progress,state)
if __name__=='__main__':main()
