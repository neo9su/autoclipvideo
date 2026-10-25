"""Guarded backend-only activation for the event-loop stall repair."""
from pathlib import Path
import hashlib,json,sqlite3,sys,datetime,subprocess,os

ROOT=Path(r'C:\Users\neo\douyin_backend')

def digest(data):return hashlib.sha256(data).hexdigest()
def atomic(path,data):
    temp=path.with_name(path.name+'.groups-tmp');temp.write_bytes(data);os.replace(temp,path)


def main(stage):
    sys.path[:0]=[str(stage),str(stage.parent/'release-v1')]
    import backend_restart_utils as maintenance
    from patch_groups_event_loop import patch
    target=ROOT/'backend'/'main.py';old=target.read_bytes();source=old.decode('utf8').replace('\r\n','\n')
    new=patch(source).encode('utf8');compile(new,str(target),'exec')
    with sqlite3.connect(ROOT/'douyin.db') as db:
        assert db.execute("select count(*) from publish_tasks where status='publishing'").fetchone()[0]==0,'Publishing active; postpone repair'
        count=db.execute('select count(*) from publish_tasks').fetchone()[0]
    plan=maintenance.backend_task_plan();assert plan['restart_task']=='DouyinBackend8899SusunInteractive','Desktop owner drift'
    pids=maintenance.backend_pids();assert len(pids)==1,'Listener count changed'
    backup=ROOT/'codex_rollbacks'/('groups-event-loop-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));backup.mkdir()
    (backup/'main.before.py').write_bytes(old)
    (backup/'manifest.json').write_text(json.dumps(dict(target=str(target),before=digest(old),after=digest(new)),indent=2))
    (backup/'task-state.json').write_text(json.dumps(plan,indent=2));(backup/'restore_tasks.py').write_text(maintenance.TASK_RECOVERY)
    (backup/'rollback.py').write_text('''from pathlib import Path
import hashlib,json,sqlite3,os
b=Path(__file__).parent;m=json.loads((b/'manifest.json').read_text());p=Path(m['target'])
with sqlite3.connect(b.parents[1]/'douyin.db') as db:assert db.execute("select count(*) from publish_tasks where status='publishing'").fetchone()[0]==0,'Publishing active'
assert hashlib.sha256(p.read_bytes()).hexdigest()==m['after'],'Source drift'
data=(b/'main.before.py').read_bytes();assert hashlib.sha256(data).hexdigest()==m['before']
t=p.with_name(p.name+'.restore-tmp');t.write_bytes(data);os.replace(t,p)
print('Original backend source restored; restart only the desktop backend while publication is idle. Database/media/GPU unchanged.')
''')
    changed=[];applied=False
    try:
        assert target.read_bytes()==old,'Source changed before activation'
        maintenance.pause_backend_tasks(plan,changed)
        for pid in pids & maintenance.backend_pids():subprocess.run(['taskkill','/PID',str(pid),'/F'],capture_output=True)
        assert not maintenance.backend_pids(),'Backend survived pause'
        atomic(target,new);applied=True
    finally:
        if not applied:atomic(target,old)
        maintenance.restore_backend_tasks(plan,changed)
    result=dict(backup=str(backup),applied=applied,publish_tasks_before=count,gpu_restarted=False,desktop_owner=plan['restart_task'])
    (backup/'verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)


if __name__=='__main__':main(Path(sys.argv[1]))
