"""Activate verified picker changes; preserve database, media, GPU services and desktop startup."""
from pathlib import Path
import hashlib,json,os,sqlite3,sys,datetime,subprocess,time

ROOT=Path(r'C:\Users\neo\douyin_backend')


def sha(data):return hashlib.sha256(data).hexdigest()
def atomic(path,data):
    temp=path.with_name(path.name+'.picker-tmp');temp.write_bytes(data);os.replace(temp,path)


def main(stage):
    sys.path.insert(0,str(stage))
    import backend_restart_utils as maintenance
    meta=json.loads((stage/'deployment.json').read_text())
    api=ROOT/'backend'/'api_codex.py';helper=ROOT/'backend'/'group_artifact_snapshot.py'
    index=ROOT/'frontend'/'dist'/'index.html';asset=index.parent/'assets'/meta['name']
    old=index.read_bytes();old_asset='index-product-loading-4d5a20a07cba.js'
    assert old.count(old_asset.encode())==1,'Frontend entry drift'
    assert sha((asset.parent/old_asset).read_bytes())==meta['old_sha'],'Frontend asset drift'
    assert sha(api.read_bytes())==meta['api_before'],'API source drift'
    assert not helper.exists(),'Helper already exists; inspect before replacing'
    assert not asset.exists(),'Asset already exists; inspect'
    for name,digest in [('api_codex.py',meta['api_after']),('group_artifact_snapshot.py',meta['helper_sha']), (meta['name'],meta['sha256'])]:
        assert sha((stage/name).read_bytes())==digest,'Staged file drift'
    with sqlite3.connect(ROOT/'douyin.db') as db:
        assert not db.execute("select id from publish_tasks where status='publishing'").fetchall(),'Publishing active; postpone restart'
        task_count=db.execute('select count(*) from publish_tasks').fetchone()[0]
    plan=maintenance.backend_task_plan()
    assert plan['restart_task']=='DouyinBackend8899SusunInteractive','Desktop owner drift'
    pids=maintenance.backend_pids();assert len(pids)==1,'Listener inventory changed'
    backup=ROOT/'codex_rollbacks'/('publish-group-loading-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));backup.mkdir()
    changes=[(api,(stage/'api_codex.py').read_bytes()),(helper,(stage/'group_artifact_snapshot.py').read_bytes()),(asset,(stage/meta['name']).read_bytes()),(index,old.replace(old_asset.encode(),meta['name'].encode()))]
    manifest=[]
    for i,(path,data) in enumerate(changes):
        before=path.read_bytes() if path.exists() else None
        if before is not None:(backup/str(i)).write_bytes(before)
        manifest.append(dict(path=str(path),backup=str(i),before=sha(before) if before is not None else None,after=sha(data)))
    (backup/'manifest.json').write_text(json.dumps(manifest,indent=2))
    (backup/'task-state.json').write_text(json.dumps(plan,indent=2))
    (backup/'restore_tasks.py').write_text(maintenance.TASK_RECOVERY)
    (backup/'rollback.py').write_text('''from pathlib import Path
import hashlib,json,os,sqlite3
b=Path(__file__).parent;items=json.loads((b/'manifest.json').read_text())
with sqlite3.connect(b.parents[1]/'douyin.db') as db:assert db.execute("select count(*) from publish_tasks where status='publishing'").fetchone()[0]==0,'Publishing active'
for item in items:assert hashlib.sha256(Path(item['path']).read_bytes()).hexdigest()==item['after'],'Deployment drift'
for item in reversed(items):
 p=Path(item['path'])
 if item['before'] is None:
  # Retain immutable frontend assets for already-open tabs; helper is unused after API restore.
  continue
 data=(b/item['backup']).read_bytes();assert hashlib.sha256(data).hexdigest()==item['before']
 temp=p.with_name(p.name+'.restore-tmp');temp.write_bytes(data);os.replace(temp,p)
print('Original API and frontend entry restored. Restart only the desktop backend while publication is idle. No database/media restore required.')
''')
    changed=[];applied=False
    try:
        maintenance.pause_backend_tasks(plan,changed)
        for pid in pids & maintenance.backend_pids():
            subprocess.run(['taskkill','/PID',str(pid),'/F'],capture_output=True)
        assert not maintenance.backend_pids(),'Backend survived pause'
        for path,data in changes:atomic(path,data)
        applied=True
    finally:
        if not applied:
            for item in reversed(manifest):
                path=Path(item['path'])
                if item['before'] is not None:atomic(path,(backup/item['backup']).read_bytes())
        maintenance.restore_backend_tasks(plan,changed)
    result=dict(backup=str(backup),task_count_before=task_count,applied=applied,desktop_owner=plan['restart_task'],gpu_restarted=False)
    (backup/'verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)


if __name__=='__main__':main(Path(sys.argv[1]))
