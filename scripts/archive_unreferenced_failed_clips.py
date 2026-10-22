"""Archive only aged failed clip jobs absent from the production database."""
import os,re,json,hashlib,tarfile,io,sqlite3,time,shutil
from pathlib import Path
BASE=Path(r'C:\Users\neo\douyin_backend\codex_rollbacks\disk-cleanup-20261021')
ROOT=Path(r'F:\douyin_recordings\clips')
DB=Path(r'C:\Users\neo\douyin_backend\douyin.db')
JOBS=Path(r'F:\douyin_recordings\jobs.db')
def durable_bytes(path,data):
    temporary=path.with_name(path.name+'.writing')
    with temporary.open('xb') as stream:
        stream.write(data);stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path)
def durable_json(path,value):durable_bytes(path,json.dumps(value,ensure_ascii=False,indent=2).encode())

def business_ids():
    ids=set()
    with sqlite3.connect('file:'+str(DB)+'?mode=ro',uri=True) as c:
        for (table,) in c.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'"):
            qt='"'+table.replace('"','""')+'"'
            cols=[x[1] for x in c.execute('pragma table_info('+qt+')') if 'TEXT' in x[2].upper()]
            if not cols:continue
            for row in c.execute('select '+','.join('"'+x.replace('"','""')+'"' for x in cols)+' from '+qt):
                for v in row:
                    if isinstance(v,str):ids.update(re.findall(r'(?<![0-9a-f])[0-9a-f]{16}(?![0-9a-f])',v.lower()))
    return ids

def validate_dirs(dirs):
    ids=business_ids()
    with sqlite3.connect('file:'+str(JOBS)+'?mode=ro',uri=True) as c:
        assert c.execute("select count(*) from clip_jobs where status not in ('done','error','cancelled','canceled')").fetchone()[0]==0,'Active clip job; postpone cleanup'
        for directory in dirs:
            p=Path(directory)
            assert p.parent==ROOT and re.fullmatch('[0-9a-f]{16}',p.name) and p.name not in ids,'Referenced or outside allowlist'
            assert not p.is_symlink() and not p.is_junction(),'Linked directory'
            assert c.execute('select status from clip_jobs where job_id=?',(p.name,)).fetchone()==('error',),'Job no longer failed'
            for q in p.rglob('*'):
                assert not q.is_symlink() and not q.is_junction(),'Linked child'
                if q.is_file():assert q.stat().st_mtime<time.time()-7*86400,'Recent file'

class HashReader:
    def __init__(self,stream):self.stream=stream;self.hash=hashlib.sha256()
    def read(self,n=-1):
        b=self.stream.read(n);self.hash.update(b);return b
class HashWriter:
    def __init__(self,stream):self.stream=stream;self.hash=hashlib.sha256()
    def write(self,b):
        n=self.stream.write(b);assert n==len(b);self.hash.update(b);return n
    def flush(self):self.stream.flush()

def make_plan():
    candidates=json.loads((BASE/'candidate-business-unreferenced.json').read_text())
    assert all(x['status']=='error' for x in candidates)
    batches=[];current=[];size=0
    for r in candidates:
        if current and size+r['bytes']>4*2**30:batches.append(current);current=[];size=0
        current.append(r['path']);size+=r['bytes']
    if current:batches.append(current)
    p=BASE/'batches.json';assert not p.exists();durable_json(p,batches);print(json.dumps({'batches':len(batches)}))

def prepare(index):
    dirs=json.loads((BASE/'batches.json').read_text())[index];validate_dirs(dirs)
    b=BASE/f'batch-{index:03d}';b.mkdir(exist_ok=False)
    assert shutil.disk_usage('C:\\').free>6*2**30,'Insufficient staging space'
    records=[]
    with (b/'clips.tar').open('xb') as output:
        writer=HashWriter(output)
        with tarfile.open(fileobj=writer,mode='w|') as archive:
            for directory in dirs:
                for q in Path(directory).rglob('*'):
                    if not q.is_file():continue
                    before=q.stat();member=str(q.relative_to(ROOT)).replace('\\','/')
                    with q.open('rb') as source:
                        reader=HashReader(source);archive.addfile(archive.gettarinfo(str(q),arcname=member),reader)
                    after=q.stat();assert before.st_size==after.st_size and before.st_mtime_ns==after.st_mtime_ns,'Source changed while copying'
                    records.append(dict(path=str(q),member=member,size=after.st_size,mtime_ns=after.st_mtime_ns,sha256=reader.hash.hexdigest()))
            manifest=json.dumps(dict(directories=dirs,files=records),ensure_ascii=False,indent=2).encode()
            info=tarfile.TarInfo('manifest.json');info.size=len(manifest);archive.addfile(info,io.BytesIO(manifest))
        writer.flush();os.fsync(output.fileno());archive_hash=writer.hash.hexdigest()
    durable_bytes(b/'manifest.json',manifest)
    result=dict(index=index,bytes=sum(x['size'] for x in records),files=len(records),archive_sha256=archive_hash,archive=str(b/'clips.tar'))
    durable_json(b/'archive-info.json',result);print(json.dumps(result),flush=True)

def finish(index,verified_sha,archive_location):
    b=BASE/f'batch-{index:03d}';info=json.loads((b/'archive-info.json').read_text());assert verified_sha==info['archive_sha256']
    manifest=json.loads((b/'manifest.json').read_text(encoding='utf-8'));validate_dirs(manifest['directories'])
    for r in manifest['files']:
        p=Path(r['path']);s=p.stat();assert s.st_size==r['size'] and s.st_mtime_ns==r['mtime_ns'],'Source changed'
        with p.open('rb') as f:
            h=hashlib.sha256()
            for data in iter(lambda:f.read(8*1024*1024),b''):h.update(data)
        assert h.hexdigest()==r['sha256'],'Source hash changed'
    durable_json(b/'external-copy.json',dict(location=archive_location,sha256=verified_sha))
    with (b/'removed.jsonl').open('x') as journal:
        for r in manifest['files']:
            p=Path(r['path']);assert p.stat().st_mtime_ns==r['mtime_ns'];p.unlink();journal.write(json.dumps(r)+'\n');journal.flush()
    for directory in manifest['directories']:
        for root,ds,fs in os.walk(directory,topdown=False):
            try:Path(root).rmdir()
            except OSError:pass
    (b/'clips.tar').unlink()
    result=dict(index=index,removed_bytes=info['bytes'],free_f_gb=round(shutil.disk_usage('F:\\').free/2**30,3))
    durable_json(b/'complete.json',result);print(json.dumps(result),flush=True)
