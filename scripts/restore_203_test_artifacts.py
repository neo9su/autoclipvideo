"""Restore the cleanup allowlist from the checksum-verified off-host tar copy."""
import sys,tarfile,json,hashlib,os,shutil
from pathlib import Path
BASE=Path(r'C:\Users\neo\douyin_backend\codex_rollbacks\disk-cleanup-20261020')
def digest_file(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
    return h.hexdigest()
def restore(archive_path):
    info=json.loads((BASE/'archive-info.json').read_text());assert digest_file(archive_path)==info['archive_sha256']
    manifest=json.loads((BASE/'manifest.json').read_text(encoding='utf-8'));roots=[Path(x) for x in manifest.get('roots',manifest.get('directories',[]))];assert roots,'No restore allowlist'
    for r in manifest['files']:
        p=Path(r['path']);assert any(p.is_relative_to(root) for root in roots)
        if p.exists():assert digest_file(p)==r['sha256'],'Existing different file; no overwrite'
    with tarfile.open(archive_path,'r') as archive:
        for r in manifest['files']:
            p=Path(r['path'])
            if p.exists():continue
            m=archive.getmember(r['member']);assert m.isfile() and m.size==r['size']
            p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.restore.tmp')
            with archive.extractfile(m) as src,tmp.open('xb') as dst:shutil.copyfileobj(src,dst,8*1024*1024)
            assert digest_file(tmp)==r['sha256'];os.replace(tmp,p);os.utime(p,ns=(r['mtime_ns'],r['mtime_ns']))
    print('All archived files restored and verified')
if __name__=='__main__':
    if len(sys.argv)==3:BASE=Path(sys.argv[1])
    restore(sys.argv[-1])
