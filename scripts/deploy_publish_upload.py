"""Activate finished-upload route and picker entry, preserving user media and task data."""
from pathlib import Path
import hashlib,json,os,sqlite3,sys,datetime,subprocess,urllib.request
ROOT=Path(r'C:\Users\neo\douyin_backend')
REGISTRATION=r'''
# Finished videos uploaded from the publishing picker are never sent to editing workers.
from publish_uploads import create_router as _create_publish_upload_router
from db import DB_PATH as _publish_upload_db
from pathlib import Path as _PublishUploadPath
app.include_router(_create_publish_upload_router(
    _publish_upload_db,
    _PublishUploadPath(os.environ.get('PUBLISH_UPLOAD_DIR', r'\\10.190.0.222\disk2\douyin-203-f-media\publish_uploads')),
))

'''

def sha(data):return hashlib.sha256(data).hexdigest()
def atomic(path,data):
    temp=path.with_name(path.name+'.upload-release-tmp');temp.write_bytes(data);os.replace(temp,path)


def main(stage):
    sys.path.insert(0,str(stage.parent/'publish-groups-20261025'/'release-v1'))
    import backend_restart_utils as maintenance
    meta=json.loads((stage/'deployment.json').read_text())
    assert json.loads((stage/'storage-probe.json').read_text())['writable'],'Shared storage is not writable by susun'
    main_path=ROOT/'backend'/'main.py';old_main=main_path.read_bytes();source=old_main.decode('utf8').replace('\r\n','\n')
    marker='_groups_list_lock = asyncio.Lock()'
    assert source.count(marker)==1 and '_create_publish_upload_router' not in source,'Backend integration drift'
    new_main=source.replace(marker,REGISTRATION+marker,1).encode('utf8');compile(new_main,str(main_path),'exec')
    index=ROOT/'frontend'/'dist'/'index.html';old_index=index.read_bytes();old_asset='index-publish-rooms-0df6aa886cec.js'
    assert old_index.count(old_asset.encode())==1,'Frontend entry drift'
    assert sha((index.parent/'assets'/old_asset).read_bytes())=='0df6aa886cec5d40ba17e35c0b763d635edc960e70bd600f9e5bb03c062dd210'
    asset=index.parent/'assets'/meta['name'];assert not asset.exists(),'New asset already exists'
    assert sha((stage/meta['name']).read_bytes())==meta['sha256'],'Staged asset drift'
    assert not (ROOT/'backend'/'publish_uploads.py').exists(),'Upload module already exists'
    changes=[(ROOT/'backend'/'publish_uploads.py',(stage/'publish_uploads.py').read_bytes())]
    policy=ROOT/'backend'/'publish_policy.py';new_policy=(stage/'publish_policy.py').read_bytes()
    if policy.exists():assert policy.read_bytes()==new_policy,'Shared publish policy differs; inspect before deployment'
    else:changes.append((policy,new_policy))
    for path,data in changes:compile(data,str(path),'exec')
    changes += [(main_path,new_main),(asset,(stage/meta['name']).read_bytes()),(index,old_index.replace(old_asset.encode(),meta['name'].encode()))]
    with sqlite3.connect(ROOT/'douyin.db') as db:
        assert not db.execute("select id from publish_tasks where status='publishing'").fetchall(),'Publishing active; postpone deployment'
        counts={table:db.execute('select count(*) from '+table).fetchone()[0] for table in ['publish_tasks','recordings','clip_groups']}
    plan=maintenance.backend_task_plan();assert plan['restart_task']=='DouyinBackend8899SusunInteractive'
    backup=ROOT/'codex_rollbacks'/('publish-upload-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));backup.mkdir()
    manifest=[]
    for n,(path,data) in enumerate(changes):
        before=path.read_bytes() if path.exists() else None
        if before is not None:(backup/str(n)).write_bytes(before)
        manifest.append(dict(path=str(path),backup=str(n),before=sha(before) if before is not None else None,after=sha(data)))
    (backup/'manifest.json').write_text(json.dumps(manifest,indent=2));(backup/'task-state.json').write_text(json.dumps(plan,indent=2));(backup/'restore_tasks.py').write_text(maintenance.TASK_RECOVERY)
    (backup/'rollback.py').write_text('''from pathlib import Path
import hashlib,json,sqlite3,os
b=Path(__file__).parent;items=json.loads((b/'manifest.json').read_text())
with sqlite3.connect(b.parents[1]/'douyin.db') as db:assert db.execute("select count(*) from publish_tasks where status='publishing'").fetchone()[0]==0,'Publishing active'
for item in items:assert hashlib.sha256(Path(item['path']).read_bytes()).hexdigest()==item['after'],'Source or entry drift'
for item in reversed(items):
 if item['before'] is None:continue
 data=(b/item['backup']).read_bytes();assert hashlib.sha256(data).hexdigest()==item['before']
 p=Path(item['path']);t=p.with_name(p.name+'.restore-tmp');t.write_bytes(data);os.replace(t,p)
print('Original frontend entry and backend integration restored. Restart desktop backend while idle. Keep uploaded videos/groups; no database rollback, no GPU restart.')
''')
    pids=maintenance.backend_pids();assert len(pids)==1
    changed=[];applied=False
    try:
        assert main_path.read_bytes()==old_main and index.read_bytes()==old_index,'Deployment drift'
        maintenance.pause_backend_tasks(plan,changed)
        for pid in pids & maintenance.backend_pids():subprocess.run(['taskkill','/PID',str(pid),'/F'],capture_output=True)
        assert not maintenance.backend_pids()
        # Keep the old frontend entry until the new route passes HTTP verification.
        for path,data in changes[:-2]:atomic(path,data)
        applied=True
    finally:
        if not applied:
            for item in reversed(manifest):
                if item['before'] is not None:atomic(Path(item['path']),(backup/item['backup']).read_bytes())
        maintenance.restore_backend_tasks(plan,changed)
    with urllib.request.urlopen('http://127.0.0.1:8899/api/publish-videos/capabilities',timeout=10) as response:
        capability=json.load(response);assert capability['min_duration']==15 and capability['max_duration']==300 and capability['auto_publish'] is False
    atomic(asset,(stage/meta['name']).read_bytes());atomic(index,changes[-1][1])
    with urllib.request.urlopen('http://127.0.0.1:8899/assets/'+meta['name'],timeout=15) as response:assert sha(response.read())==meta['sha256']
    with sqlite3.connect(ROOT/'douyin.db') as db:after={table:db.execute('select count(*) from '+table).fetchone()[0] for table in counts}
    result=dict(backup=str(backup),capabilities=capability,counts_before=counts,counts_after=after,asset=meta['name'],gpu_restarted=False)
    (backup/'verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)


if __name__=='__main__':main(Path(sys.argv[1]))
