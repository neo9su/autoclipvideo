"""Stage only; never interrupt active media work. Copy beside patch module on 203."""
from pathlib import Path
import datetime,hashlib,json,os
r=Path(r'C:\Users\neo\douyin_backend');target=r/'backend/main.py';old=target.read_bytes()
from patch_pipeline_stats import patch
new=patch(old.decode('utf8').replace('\r\n','\n')).encode('utf8')
backup=r/'codex_rollbacks'/('pipeline-stats-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));backup.mkdir()
(backup/'main.before.py').write_bytes(old)
manifest=dict(target=str(target),before=hashlib.sha256(old).hexdigest(),after=hashlib.sha256(new).hexdigest(),restart_pending=True)
(backup/'manifest.json').write_text(json.dumps(manifest,indent=2))
(backup/'rollback.py').write_text("from pathlib import Path\nimport json,hashlib,os\nb=Path(__file__).parent;m=json.loads((b/'manifest.json').read_text());p=Path(m['target']);assert hashlib.sha256(p.read_bytes()).hexdigest()==m['after'],'Source drift';data=(b/'main.before.py').read_bytes();assert hashlib.sha256(data).hexdigest()==m['before'];t=p.with_name(p.name+'.restore-tmp');t.write_bytes(data);os.replace(t,p);print('Source restored; restart desktop backend only when media and publication are idle.')\n")
assert target.read_bytes()==old,'Concurrent source modification'
tmp=target.with_name('main.py.stats-tmp');tmp.write_bytes(new);os.replace(tmp,target)
print(json.dumps(dict(backup=str(backup),source_patched=True,restarted=False)))
