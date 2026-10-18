"""Run on 220: archive inactive 203 clip intermediates to 222 with checked receipts."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
import shlex
import subprocess
import sys
import threading
import uuid


def run_batch(plans,operation,workers=2):
    if workers not in (1,2):raise ValueError('Only one or two transfers are allowed')
    stop=threading.Event();results=[];errors=[]
    def work(plan):
        if stop.is_set():return None
        try:return operation(plan)
        except Exception:
            stop.set();raise
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(work,plan):plan['job_id'] for plan in plans}
        for future in as_completed(futures):
            try:
                result=future.result()
                if result is not None:
                    results.append(result);print(json.dumps({'stage':'archived_and_reclaimed',**result}),flush=True)
            except Exception as error:
                errors.append({'job_id':futures[future],'error_type':type(error).__name__})
                print(json.dumps({'stage':'stopped_after_error',**errors[-1]}),flush=True)
    return results,errors


def archive_one(plan,admin,archive):
    job=plan['job_id']
    if len(job)!=16 or any(c not in '0123456789abcdef' for c in job):raise ValueError('Invalid job')
    def linux(code,payload=None):
        return subprocess.run(['ssh','-o','BatchMode=yes','neo@10.190.0.222','python3 -c '+shlex.quote(code)],input=payload,text=True,capture_output=True,check=True,timeout=600).stdout
    def windows(code):
        return subprocess.run(['ssh','-o','BatchMode=yes','dyy',r'C:\Python313\python.exe -X utf8 -'],input=code,text=True,capture_output=True,check=True,timeout=600).stdout
    stage=archive+'/'+job+'.scp-partial-'+uuid.uuid4().hex
    prepare='ROOT='+repr(archive)+'\nSTAGE='+repr(stage)+'\n'+r'''
import pathlib,json,sys
sys.path.insert(0,ROOT);import archive_clip_temps as m
plan=json.load(sys.stdin);m.validate(plan);final=pathlib.Path(ROOT)/plan['job_id']
if final.exists():
 old=json.loads((final/'manifest.json').read_text());assert m.fingerprint(old)==m.fingerprint(plan),'Existing archive differs'
 print(json.dumps({'existing':True}))
else:
 stage=pathlib.Path(STAGE);stage.mkdir(parents=True,exist_ok=False);(stage/'manifest.json').write_text(json.dumps(plan));print(json.dumps({'existing':False}))
'''
    existing=json.loads(linux(prepare,json.dumps(plan)))['existing']
    if not existing:
        sources=['dyy:F:/douyin_recordings/clips/'+job+'/'+f['name'] for f in plan['files']]
        subprocess.run(['scp','-3','-B','-p',*sources,'neo@10.190.0.222:'+stage+'/'],capture_output=True,check=True,timeout=1800)
    verify='ROOT='+repr(archive)+'\nSTAGE='+repr(archive+'/'+job if existing else stage)+'\nEXISTING='+repr(existing)+'\n'+r'''
import pathlib,json,sys,os
sys.path.insert(0,ROOT);import archive_clip_temps as m
p=pathlib.Path(STAGE);plan=json.loads((p/'manifest.json').read_text());m.validate(plan)
for f in plan['files']:
 target=p/f['name'];assert target.stat().st_size==f['bytes'] and m.digest(target)==f['sha256'],'Archive mismatch'
 os.utime(target,ns=(f['mtime_ns'],f['mtime_ns']))
if not EXISTING:
 final=pathlib.Path(ROOT)/plan['job_id'];assert not final.exists();p.rename(final)
print(json.dumps({'fingerprint':m.fingerprint(plan),'files':len(plan['files']),'bytes':sum(f['bytes'] for f in plan['files'])}))
'''
    receipt=json.loads(linux(verify))
    reclaim='ADMIN='+repr(admin)+'\nJOB='+repr(job)+'\nRECEIPT='+repr(receipt)+'\n'+r'''
import pathlib,sys,json,sqlite3
admin=pathlib.Path(ADMIN);sys.path.insert(0,str(admin));import archive_clip_temps as m
plan=json.loads((admin/(JOB+'.json')).read_text());db=sqlite3.connect('file:F:/douyin_recordings/jobs.db?mode=ro',uri=True)
assert db.execute('select status from clip_jobs where job_id=?',(JOB,)).fetchone()[0] in ['done','error']
con=sqlite3.connect(r'C:\Users\neo\douyin_backend\douyin.db');protected=set()
for table in ['recordings','recording_clips','clip_groups','publish_tasks']:
 fields=[r[1] for r in con.execute('pragma table_info('+table+')') if r[1] in ['filename','clip_filename','video_path','merged_filename','capcut_export_filename'] or r[1].endswith('_final_video')]
 for row in con.execute('select '+','.join(fields)+' from '+table):
  for value in row:
   if value:protected.add(str(value).replace(chr(92),'/').split('/')[-1].casefold())
assert not any(f['name'].casefold() in protected for f in plan['files']),'New protected reference'
(admin/(JOB+'.receipt.json')).write_text(json.dumps(RECEIPT),encoding='utf-8')
result=m.reclaim(r'F:\douyin_recordings\clips',plan,RECEIPT)
(admin/(JOB+'.applied.json')).write_text(json.dumps(result),encoding='utf-8');print(json.dumps(result))
'''
    result=json.loads(windows(reclaim));return dict(result,job_id=job)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--admin',required=True);parser.add_argument('--archive',required=True);parser.add_argument('--workers',type=int,default=2)
    args=parser.parse_args();plans=json.load(sys.stdin)
    results,errors=run_batch(plans,lambda plan:archive_one(plan,args.admin,args.archive),args.workers)
    report={'stage':'complete' if not errors and len(results)==len(plans) else 'incomplete','jobs':len(results),'files':sum(r['files'] for r in results),'gb':round(sum(r['bytes'] for r in results)/1073741824,3),'errors':errors}
    print(json.dumps(report),flush=True)
    raise SystemExit(0 if report['stage']=='complete' else 1)
