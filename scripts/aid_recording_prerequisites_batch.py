"""Resume a bounded ASR prerequisite batch; no legacy workers or business DB writes."""
import json
from pathlib import Path
import subprocess
import sys
from aid_transcribe_recording import run, save

BATCH = Path(r'C:\Users\neo\douyin_backend\codex_operations\production-20261025')


def main(limit=3):
    sys.path.insert(0, r'C:\Users\neo\douyin_backend\backend')
    from recording_paths import resolve_recording_path
    rows = json.loads((BATCH/'inventory.json').read_text(encoding='utf-8'))['recordings']
    progress = BATCH/'prerequisites-batch.json'
    state = json.loads(progress.read_text(encoding='utf-8')) if progress.exists() else {
        'stage':'ASR_PREREQUISITES_ONLY', 'source_deleted':False, 'business_db_changed':False, 'items':[]}
    state.update(finished=False,bounded_limit=limit)
    save(progress,state)
    done = {item['id'] for item in state['items']}
    completed = sum(item['status']=='TRANSCRIBED_NOT_CLIPPED' for item in state['items'])
    for row in rows:
        if completed >= limit or (BATCH/'PAUSE_PREREQUISITES').exists():
            break
        if row['transcribed']==2 or row['id'] in done or row['id']==45409:
            continue
        item = {'id':row['id'],'filename':row['filename']}
        try:
            raw = resolve_recording_path(row['filename'])
            source = Path(raw) if raw else None
            if not source or not source.is_file():
                raise ValueError('missing_or_inaccessible')
            probe = subprocess.run(['ffprobe','-v','error','-show_entries',
                'stream=codec_type,width,height:format=duration','-of','json',str(source)],
                capture_output=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if probe.returncode:
                raise ValueError('invalid_container')
            meta=json.loads(probe.stdout)
            video=next(s for s in meta['streams'] if s.get('codec_type')=='video')
            if min(video['width'],video['height'])<1080 or max(video['width'],video['height'])<1920:
                raise ValueError('below_1080p_preserved')
            if not 0<float(meta['format']['duration'])<=1800:
                raise ValueError('needs_long_recording_audio_chunking')
            state['active_recording_id']=row['id'];save(progress,state)
            run(row['id'],BATCH)
            result=json.loads((BATCH/f"recording-{row['id']}.json").read_text(encoding='utf-8'))
            item.update(status=result['phase'],job_id=result.get('job_id'))
            if item['status']=='TRANSCRIBED_NOT_CLIPPED': completed+=1
        except Exception as exc:
            item.update(status='PREFLIGHT_OR_CLIENT_ERROR',reason=str(exc)[:300])
        state.pop('active_recording_id',None)
        state['items'].append(item);save(progress,state)
    state.pop('active_recording_id',None)
    state.update(completed_transcripts=completed,bounded_limit=limit,finished=True)
    save(progress,state)


if __name__=='__main__':
    main()
