"""Download a fixed official snapshot to staging; verify before atomic activation."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import threading
from urllib import request


def verify(path, item):
    if path.stat().st_size!=item['size']:
        raise ValueError('File size mismatch: '+item['name'])
    if item.get('sha256'):
        digest=hashlib.sha256()
        with path.open('rb') as f:
            while block:=f.read(8*1024*1024):digest.update(block)
        valid=digest.hexdigest()==item['sha256']
    else:
        data=path.read_bytes()
        valid=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()==item['git_sha1']
    if not valid:raise ValueError('Checksum mismatch: '+item['name'])


def download_file(base, folder, item):
    name=item['name']
    if Path(name).name!=name or name in ('.','..'):
        raise ValueError('Only explicitly listed root-level model files are allowed')
    target=folder/name
    if target.exists():verify(target,item);return
    partial=target.with_name(target.name+'.partial')
    offset=partial.stat().st_size if partial.exists() else 0
    if offset>item['size']:raise ValueError('Partial file exceeds expected size')
    if offset<item['size']:
        req=request.Request(base+'/'+name+'?download=true',headers={'Range':f'bytes={offset}-','User-Agent':'Codex-Pinned-Model-Downloader/1'})
        with request.urlopen(req,timeout=90) as response:
            if offset and (response.status!=206 or not response.headers.get('Content-Range','').startswith(f'bytes {offset}-')):
                raise ValueError('Server did not honour resume range')
            with partial.open('ab' if offset else 'wb') as f:
                while block:=response.read(8*1024*1024):f.write(block)
    verify(partial,item);partial.rename(target)


def install(manifest, destination):
    destination=Path(destination)
    if destination.exists():
        for item in manifest['files']:verify(destination/item['name'],item)
        return {'state':'ready','already_present':True}
    stage=destination.with_name(destination.name+'.staging');stage.mkdir(parents=True,exist_ok=True)
    missing=sum(item['size']-(stage/item['name']).stat().st_size if (stage/item['name']).exists() else item['size'] for item in manifest['files'])
    # Allow room for ordinary system activity; never clear other models/media.
    if shutil.disk_usage(stage).free<missing+5*1024**3:raise ValueError('Insufficient free disk space')
    status=stage/'download-status.json';lock=threading.Lock();state={'state':'downloading','model':manifest['model'],'revision':manifest['revision'],'verified_files':[]}
    def save():
        tmp=status.with_suffix('.tmp');tmp.write_text(json.dumps(state,indent=2),encoding='utf-8');tmp.replace(status)
    save()
    base='https://huggingface.co/'+manifest['model']+'/resolve/'+manifest['revision']
    def run(item):
        download_file(base,stage,item)
        with lock:state['verified_files'].append(item['name']);save()
        print('Verified '+item['name'],flush=True)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(run,manifest['files']))
        (stage/'source_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        state['state']='verified';save()
        stage.rename(destination)
        return {'state':'ready','destination':str(destination),'revision':manifest['revision']}
    except BaseException as e:
        with lock:state.update(state='failed',error=type(e).__name__+': '+str(e));save()
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',required=True);p.add_argument('--destination',required=True);a=p.parse_args()
    print(json.dumps(install(json.loads(Path(a.manifest).read_text(encoding='utf-8')),a.destination)),flush=True)
