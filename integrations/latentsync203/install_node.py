from pathlib import Path
import json,hashlib,datetime,sys,subprocess,os
r=Path(r'C:\ProgramData\AIDGpuScheduler');model=Path(r'F:\aid-models\latentsync-1.5');name='latentsync-15-203'
assert (model/'weights.log').read_text().endswith('WEIGHTS_READY\n')
assert 'DEPENDENCIES_READY' in (model/'bootstrap.log').read_text()
p=r/'agent.json';before=p.read_bytes();c=json.loads(before.decode('utf-8-sig'));assert name not in c['profiles']
worker=r/'adapters'/name/'gpu_latentsync_worker.py';worker.parent.mkdir(parents=True,exist_ok=True)
data=(model/'gpu_latentsync_worker.py').read_bytes();compile(data,str(worker),'exec')
entry={'runCommand':[r'C:\Python313\python.exe',str(worker),'{job_file}'],'resultRequired':True,'startCommand':['powershell','-NoProfile','-Command',"$ErrorActionPreference='Stop'; Invoke-RestMethod -Method Post http://127.0.0.1:8098/gpu/release -TimeoutSec 60 | Out-Null; Invoke-RestMethod -Method Post http://127.0.0.1:8879/api/gpu/release -TimeoutSec 60 | Out-Null"],'startTimeoutSeconds':150,'allowedProcessPatterns':[r'(?i)gpu_latentsync_worker\.py',r'(?i)latentsync-1\.5',r'(?i)omnivoice_service\.py.*--port 8879',r'(?i)scripts\.inference',r'(?i)ffmpeg\.exe.*lipsync-']}
c['profiles'][name]=entry;after=json.dumps(c,indent=2).encode()
b=model/'backups'/datetime.datetime.now().strftime('%Y%m%d-%H%M%S');b.mkdir(parents=True);(b/'agent.before.json').write_bytes(before);(b/'manifest.json').write_text(json.dumps({'config':str(p),'before':hashlib.sha256(before).hexdigest(),'after':hashlib.sha256(after).hexdigest(),'worker':hashlib.sha256(data).hexdigest()}))
(b/'rollback.py').write_text("from pathlib import Path\nimport json,hashlib,os\nb=Path(__file__).parent;m=json.loads((b/'manifest.json').read_text());p=Path(m['config']);assert hashlib.sha256(p.read_bytes()).hexdigest()==m['after'];p.write_bytes((b/'agent.before.json').read_bytes());print('Restart idle AID agent after restoring config')\n")
assert p.read_bytes()==before;worker.write_bytes(data);tmp=p.with_suffix('.lipsync.tmp');tmp.write_bytes(after);os.replace(tmp,p)
print(json.dumps({'backup':str(b),'profile':name,'restart_required':True}))
