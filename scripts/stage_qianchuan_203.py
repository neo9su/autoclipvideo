"""203 AID administration: add one fixed worker/config entry, retain rollback."""
from pathlib import Path
import datetime,hashlib,json,os,subprocess
ROOT=Path(r'C:\ProgramData\AIDGpuScheduler');NAME='qianchuan-render-203'

def digest(data):return hashlib.sha256(data).hexdigest()
def atomic(path,data):
 temp=path.with_name(path.name+'.stage-tmp');temp.write_bytes(data);os.replace(temp,path)
def stage(worker_source,entry):
 config=ROOT/'agent.json';before=config.read_bytes();value=json.loads(before.decode('utf-8-sig'))
 assert value['nodeId']=='gpu-203' and value['executionMode']=='enforce'
 assert NAME not in value['profiles'],'Profile already configured; inspect before changing'
 worker=ROOT/'adapters'/NAME/'gpu_qianchuan_render_worker.py';assert not worker.exists()
 assert Path(r'C:\ProgramData\chocolatey\bin\ffmpeg.exe').is_file()
 assert Path(r'C:\ProgramData\chocolatey\bin\ffprobe.exe').is_file()
 compile(worker_source,str(worker),'exec');value['profiles'][NAME]=entry;after=json.dumps(value,ensure_ascii=False,indent=2).encode('utf8')
 backup=ROOT/'backups'/('qianchuan-203-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));backup.mkdir()
 (backup/'agent.before.json').write_bytes(before)
 xml=subprocess.run(['powershell','-NoProfile','-Command',"Export-ScheduledTask -TaskName 'AID GPU Scheduler Agent'"],capture_output=True,check=True).stdout
 (backup/'agent-task.xml').write_bytes(xml)
 manifest=dict(config=str(config),before=digest(before),after=digest(after),worker=str(worker),worker_sha=digest(worker_source.encode('utf8')))
 (backup/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
 (backup/'rollback.py').write_text(ROLLBACK,encoding='utf8')
 assert config.read_bytes()==before,'Concurrent agent edit'
 worker.parent.mkdir(parents=True);worker.write_text(worker_source,encoding='utf8')
 try:atomic(config,after)
 except BaseException:worker.unlink();raise
 print(json.dumps(dict(backup=str(backup),profile=NAME,restarted=False,worker_sha=manifest['worker_sha'])))
 return backup
ROLLBACK=r'''from pathlib import Path
import json,hashlib,os
b=Path(__file__).parent;m=json.loads((b/'manifest.json').read_text());p=Path(m['config']);w=Path(m['worker'])
assert hashlib.sha256(p.read_bytes()).hexdigest()==m['after'],'Agent config drift'
assert hashlib.sha256(w.read_bytes()).hexdigest()==m['worker_sha'],'Worker drift'
data=(b/'agent.before.json').read_bytes();assert hashlib.sha256(data).hexdigest()==m['before']
t=p.with_name(p.name+'.rollback-tmp');t.write_bytes(data);os.replace(t,p);w.unlink()
print('203 config restored. Restart only the idle AID agent; models and production backend untouched.')
'''
