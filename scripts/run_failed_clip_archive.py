"""Run on 220: pull, hash-verify, then authorize removal of one archived batch."""
from pathlib import Path
import subprocess,json,hashlib,os,sys
SOURCE=Path(__file__).with_name('archive_unreferenced_failed_clips.py').read_text()
DEST=Path.home()/'douyin-cleanup-archive'/'disk-cleanup-20261021'
def remote(call):
    r=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=4','dyy',r'C:\Python313\python.exe -X utf8 -'],input=(SOURCE+'\n'+call+'\n').encode(),capture_output=True,timeout=900)
    if r.returncode:raise RuntimeError(r.stderr.decode(errors='replace')[-2500:])
    lines=[x for x in r.stdout.decode().splitlines() if x.startswith('{')]
    return json.loads(lines[-1])
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(8*1024*1024),b''):h.update(chunk)
    return h.hexdigest()
def main():
    DEST.mkdir(parents=True,exist_ok=True)
    count=remote("print(json.dumps({'count':len(json.loads((BASE/'batches.json').read_text()))}))")['count']
    for i in range(count):
        b=DEST/f'batch-{i:03d}';b.mkdir(exist_ok=True)
        if (b/'complete.json').exists():continue
        print(json.dumps({'phase':'archiving','batch':i,'total':count}),flush=True)
        state=remote(f"b=BASE/'batch-{i:03d}';print(json.dumps({{'done':json.loads((b/'complete.json').read_text()) if (b/'complete.json').exists() else None,'prepared':json.loads((b/'archive-info.json').read_text()) if (b/'archive-info.json').exists() else None,'exists':b.exists()}}))")
        if state['done']:
            assert (b/'clips.tar').exists() and sha(b/'clips.tar')==state['prepared']['archive_sha256'],'Missing verified recovery archive'
            (b/'complete.json').write_text(json.dumps(state['done']));continue
        if state['exists'] and not state['prepared']:raise RuntimeError('Incomplete source archive; inspect before retry')
        info=state['prepared'] or remote(f'prepare({i})')
        raw=info['archive'].replace('\\','/')
        archive=b/'clips.tar';part=b/'clips.tar.part'
        subprocess.run(['scp','-q','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=4','dyy:'+raw,str(part)],check=True,timeout=900)
        assert sha(part)==info['archive_sha256'],'Off-host checksum mismatch; no removal'
        with part.open('rb') as stream:os.fsync(stream.fileno())
        os.replace(part,archive)
        for name in ['manifest.json','archive-info.json']:
            subprocess.run(['scp','-q','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=4','dyy:'+raw.rsplit('/',1)[0]+'/'+name,str(b/name)],check=True,timeout=60)
        print(json.dumps({'phase':'verified_off_host','batch':i,'bytes':info['bytes']}),flush=True)
        result=remote(f'finish({i},{info["archive_sha256"]!r},{("10.190.0.220:"+str(archive))!r})')
        (b/'complete.json').write_text(json.dumps(result));print(json.dumps({'phase':'complete',**result}),flush=True)
    print(json.dumps({'all_complete':True,'batches':count}),flush=True)
if __name__=='__main__':main()
