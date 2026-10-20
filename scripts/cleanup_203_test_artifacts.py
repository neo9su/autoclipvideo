"""Archive an explicit allowlist. Remove only after an external verified copy exists."""
from pathlib import Path
import hashlib,json,os,tarfile,shutil,datetime
ROOTS=[Path(r'C:\Users\neo\AppData\Local\Temp\pip-unpack-limr2yyp'),Path(r'C:\douyin_login\_test_preview'),Path(r'F:\douyin_recordings\_opening_fix_audio_backup')]
BASE=Path(r'C:\Users\neo\douyin_backend\codex_rollbacks\disk-cleanup-20261020')
def digest(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()
def prepare():
    BASE.mkdir(exist_ok=False)
    records=[]
    for i,root in enumerate(ROOTS):
        for p in root.rglob('*'):
            if p.is_symlink() or p.is_junction():raise RuntimeError('Link in allowlist')
            if p.is_file():
                s=p.stat();records.append(dict(path=str(p),member=str(Path(str(i))/p.relative_to(root)).replace('\\','/'),size=s.st_size,mtime_ns=s.st_mtime_ns,sha256=digest(p)))
    (BASE/'manifest.json').write_text(json.dumps(dict(roots=list(map(str,ROOTS)),files=records),ensure_ascii=False,indent=2),encoding='utf-8')
    with tarfile.open(BASE/'artifacts.tar','w') as archive:
        for r in records:archive.add(r['path'],arcname=r['member'],recursive=False)
        archive.add(BASE/'manifest.json',arcname='manifest.json')
    info=dict(bytes=sum(r['size'] for r in records),files=len(records),archive_sha256=digest(BASE/'artifacts.tar'),archive=str(BASE/'artifacts.tar'))
    (BASE/'archive-info.json').write_text(json.dumps(info,indent=2));print(json.dumps(info),flush=True)
def finish(verified_sha,remote_archive):
    info=json.loads((BASE/'archive-info.json').read_text());assert verified_sha==info['archive_sha256']
    data=json.loads((BASE/'manifest.json').read_text(encoding='utf-8'));records=data['files']
    # Fail closed before any removal if a source changed after archival.
    for r in records:
        p=Path(r['path']);assert any(p.is_relative_to(root) for root in ROOTS)
        assert p.stat().st_size==r['size'] and digest(p)==r['sha256'],'Source changed'
    (BASE/'external-copy.json').write_text(json.dumps(dict(archive=remote_archive,sha256=verified_sha,verified_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())))
    removed=0
    with (BASE/'removed.jsonl').open('a',encoding='utf-8') as journal:
        for r in records:
            p=Path(r['path']);assert p.stat().st_mtime_ns==r['mtime_ns'],'Source modified'
            p.unlink();removed+=r['size'];journal.write(json.dumps(dict(path=str(p),bytes=r['size']))+'\n');journal.flush()
    for root in ROOTS:
        for b,ds,fs in os.walk(root,topdown=False):
            try:Path(b).rmdir()
            except OSError:pass
    (BASE/'artifacts.tar').unlink() # Verified off-host tar remains the recovery source.
    print(json.dumps(dict(removed_bytes=removed,free_gb={d:round(shutil.disk_usage(d).free/2**30,3) for d in ['C:\\','F:\\']})),flush=True)
if __name__=='__main__':prepare()
