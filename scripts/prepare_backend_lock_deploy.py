"""Generate a conditional code-only deployment for the backend startup lock."""
from pathlib import Path


def build():
    module = (Path(__file__).parents[1] / 'backend/backend_instance_lock.py').read_text()
    return 'MODULE = '+repr(module)+'\n'+r'''
from pathlib import Path
import datetime,hashlib,json,os
root=Path(r'C:\Users\neo\douyin_backend')
main=root/'backend/main.py';module=root/'backend/backend_instance_lock.py'
assert not module.exists(), 'Lock module already exists; inspect first'
old=main.read_bytes();text=old.decode('utf-8')
a='from db import init_db, DB_PATH, aio_connect'
b='@asynccontextmanager\nasync def lifespan('
normalized=text.replace('\r\n','\n')
assert normalized.count(a)==1 and normalized.count(b)==1
assert 'single_backend_instance' not in normalized
# Single-line insertion preserves existing mixed line endings.
text=text.replace(a,'from backend_instance_lock import single_backend_instance\n'+a,1)
marker='@asynccontextmanager\r\nasync def lifespan(' if b not in text else b
assert text.count(marker)==1
text=text.replace(marker,'@single_backend_instance(Path(DB_PATH).resolve().with_suffix(".backend.lock"))\n'+marker,1)
compile(text,str(main),'exec');compile(MODULE,str(module),'exec')
changes=[(module,None,MODULE.encode()),(main,old,text.encode())]
backup=root/'codex_rollbacks'/('backend-instance-lock-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir();manifest=[]
for i,(p,before,after) in enumerate(changes):
 name=str(i)+'.before'
 if before is not None:(backup/name).write_bytes(before)
 manifest.append(dict(target=str(p),backup=name,before=hashlib.sha256(before).hexdigest() if before is not None else None,after=hashlib.sha256(after).hexdigest()))
(backup/'manifest.json').write_text(json.dumps(manifest,indent=2))
(backup/'rollback.py').write_text("""from pathlib import Path
import json,hashlib,os
b=Path(__file__).parent
items=json.loads((b/'manifest.json').read_text())
for m in items:
 p=Path(m['target']);current=hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
 assert current in (m['before'],m['after']), 'Source drift; abort'
 if m['before'] is not None:assert hashlib.sha256((b/m['backup']).read_bytes()).hexdigest()==m['before']
for m in reversed(items):
 p=Path(m['target'])
 if m['before'] is None:p.unlink(missing_ok=True)
 else:
  t=p.with_suffix('.rollback.tmp');t.write_bytes((b/m['backup']).read_bytes());os.replace(t,p)
print('Code restored. Restart backend when idle. No database restored.')
""")
for p,before,after in changes:
 assert (p.read_bytes() if p.exists() else None)==before, 'Source drift'
for p,before,after in changes:
 t=p.with_suffix('.codex.tmp');t.write_bytes(after);os.replace(t,p)
print(json.dumps(dict(backup=str(backup),files=manifest)))
'''


if __name__ == '__main__':
    print(build())
