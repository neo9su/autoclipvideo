"""Storage-only reversible migration of explicitly verified completed-job caches."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil

ROOT=Path('/home/neo/.local/state/aid-gpu-scheduler/agent/jobs')
DEST=Path('/mnt/disk2/aid-gpu-job-cache-archive/douyin-20261025')


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def save(path,data):
    tmp=path.with_suffix('.writing');tmp.write_text(json.dumps(data,indent=2));os.replace(tmp,path)


def migrate(jobs):
    assert jobs and all(j['status']=='SUCCEEDED' and j['node']=='gpu-222' for j in jobs)
    DEST.mkdir(parents=True,exist_ok=True,mode=0o700)
    manifest=DEST/'manifest.json'
    state=json.loads(manifest.read_text()) if manifest.exists() else {'items':[],'scope':'completed input cache replicas only'}
    for job in jobs:
        src=ROOT/f"job-{int(job['id'])}-artifacts";dst=DEST/src.name
        if src.is_symlink():
            assert src.resolve()==dst.resolve() and any(i['id']==job['id'] and i['phase']=='linked' for i in state['items'])
            continue
        if not src.is_dir():continue
        assert src.parent==ROOT and not dst.exists(),'Unexpected cache/archive state; inspect before retry'
        files=list(src.iterdir());assert files and all(f.is_file() and not f.is_symlink() for f in files)
        needed=sum(f.stat().st_size for f in files)
        assert shutil.disk_usage(DEST).free>needed+1024**3
        dst.mkdir(mode=0o700)
        item={'id':job['id'],'source':str(src),'destination':str(dst),'phase':'copying','files':[]}
        state['items'].append(item);save(manifest,state)
        for f in files:
            stat=f.stat();target=dst/f.name
            shutil.copy2(f,target)
            expected=digest(f);assert digest(target)==expected
            assert (f.stat().st_size,f.stat().st_mtime_ns)==(stat.st_size,stat.st_mtime_ns)
            item['files'].append({'name':f.name,'bytes':stat.st_size,'sha256':expected});save(manifest,state)
        item['phase']='verified';save(manifest,state)
        retiring=src.with_name(src.name+'.verified-migrating');assert not retiring.exists()
        os.rename(src,retiring)
        try:
            src.symlink_to(dst,target_is_directory=True)
            assert all(digest(src/f['name'])==f['sha256'] for f in item['files'])
        except BaseException:
            if src.is_symlink():src.unlink()
            os.rename(retiring,src)
            raise
        # Only discard the verified duplicate cache after the disk2 copy and original-path link both pass.
        shutil.rmtree(retiring)
        item['phase']='linked';save(manifest,state)
        print(json.dumps({'id':job['id'],'moved_bytes':needed,'root_free_bytes':shutil.disk_usage('/').free}),flush=True)
    return state


def restore():
    state=json.loads((DEST/'manifest.json').read_text())
    for item in state['items']:
        if item['phase']!='linked':continue
        src=Path(item['source']);dst=Path(item['destination'])
        assert src.is_symlink() and src.resolve()==dst.resolve()
        assert shutil.disk_usage(ROOT).free>sum(f['bytes'] for f in item['files'])+1024**3
        stage=src.with_name(src.name+'.restore-copy');assert not stage.exists()
        shutil.copytree(dst,stage)
        assert all(digest(stage/f['name'])==f['sha256'] for f in item['files'])
        src.unlink();os.rename(stage,src)
        item['phase']='restored';save(DEST/'manifest.json',state)
        # Keep the archive as the rollback backup.
    return state


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['migrate','restore']);p.add_argument('--jobs',type=Path)
    a=p.parse_args()
    if a.mode=='migrate':assert a.jobs;migrate(json.loads(a.jobs.read_text()))
    else:restore()
