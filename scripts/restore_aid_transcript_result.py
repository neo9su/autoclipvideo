"""Restore one eligible transcript from a verified AID result, without clipping."""
from pathlib import Path
import datetime,hashlib,json,os,re,sqlite3
ROOT=Path(r'C:\Users\neo\douyin_backend');BATCH=ROOT/'codex_operations/failed-retry-20261025'

def validated_subtitle(state):
    duration=float(state['source_video']['format']['duration']);assert 28<=duration<=1800
    subtitle=Path(state['transcript']).read_bytes();assert hashlib.sha256(subtitle).hexdigest()==state['transcript_sha256']
    text=subtitle.decode('utf-8-sig');times=re.findall(r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})',text)
    assert times and '-->' in text
    assert max(int(h)*3600+int(m)*60+int(s)+int(ms)/1000 for h,m,s,ms in times)<=duration+1
    return duration,subtitle

def main(recording_id=44964):
    state=json.loads((BATCH/f'recording-{recording_id}.json').read_text())
    assert state['phase']=='TRANSCRIBED_NOT_CLIPPED'
    duration,subtitle=validated_subtitle(state)
    target=Path(state['source']).with_suffix('.srt');source=Path(state['source']);assert source.is_file()
    db=sqlite3.connect(ROOT/'douyin.db',timeout=15);db.row_factory=sqlite3.Row
    before=dict(db.execute('SELECT * FROM recordings WHERE id=?',(recording_id,)).fetchone())
    assert before['transcribed']==-1 and before['local_deleted']==0 and before['clipped']!=1,'State changed'
    backup=ROOT/'codex_rollbacks'/('aid-asr-restore-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));backup.mkdir()
    old=target.read_bytes() if target.exists() else None
    if old is not None:(backup/'subtitle.before').write_bytes(old)
    after=dict(transcribed=2,transcribe_error=None,synced=1,gpu_job_id=None,duration_seconds=duration,duration_status='accepted',skip_reason=None)
    (backup/'manifest.json').write_text(json.dumps(dict(before=before,after=after,target=str(target),subtitle_before=old is not None,subtitle_after_sha256=hashlib.sha256(subtitle).hexdigest()),ensure_ascii=False,indent=2),encoding='utf8')
    (backup/'rollback.py').write_text(ROLLBACK,encoding='utf8')
    try:
        db.execute('BEGIN IMMEDIATE');assert dict(db.execute('SELECT * FROM recordings WHERE id=?',(recording_id,)).fetchone())==before
        tmp=target.with_name(target.name+'.aid-restore-tmp');tmp.write_bytes(subtitle);os.replace(tmp,target)
        db.execute('UPDATE recordings SET '+','.join(k+'=?' for k in after)+' WHERE id=?',list(after.values())+[recording_id]);db.commit()
    except BaseException:
        db.rollback()
        if old is None:target.unlink(missing_ok=True)
        else:target.write_bytes(old)
        raise
    finally:db.close()
    result=dict(recording_id=recording_id,restored_transcription=True,source_changed=False,clip_submitted=False,backup=str(backup),aid_job_id=state['job_id'])
    (BATCH/'restore-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(result))

ROLLBACK=r'''from pathlib import Path
import sqlite3,json,hashlib,os
b=Path(__file__).parent;m=json.loads((b/'manifest.json').read_text(encoding='utf8'));db=sqlite3.connect(b.parents[1]/'douyin.db');db.row_factory=sqlite3.Row
try:
 db.execute('BEGIN IMMEDIATE');row=dict(db.execute('SELECT * FROM recordings WHERE id=?',(m['before']['id'],)).fetchone());assert row==m['before']|m['after'],'Processing advanced; refuse rollback';p=Path(m['target']);assert hashlib.sha256(p.read_bytes()).hexdigest()==m['subtitle_after_sha256'],'Subtitle changed'
 if m['subtitle_before']:p.write_bytes((b/'subtitle.before').read_bytes())
 else:p.unlink()
 keys=list(m['after']);db.execute('UPDATE recordings SET '+','.join(k+'=?' for k in keys)+' WHERE id=?',[m['before'][k] for k in keys]+[m['before']['id']]);db.commit()
finally:db.close()
'''
if __name__=='__main__':main()
