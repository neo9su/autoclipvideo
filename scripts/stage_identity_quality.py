"""Back up and stage only two reviewed function changes on203."""
from pathlib import Path
import datetime
import hashlib
import json
import sys
from patch_identity_quality import patch_analyzer, patch_editor

ROOT=Path(r'C:\Users\neo\douyin_backend')

def main():
    changes=[]
    for name,patch in [('analyzer.py',patch_analyzer),('editor.py',patch_editor)]:
        target=ROOT/'backend'/name
        before=target.read_bytes()
        after=patch(before.decode('utf-8-sig')).encode('utf-8')
        compile(after,str(target),'exec')
        changes.append((target,before,after))
    backup=ROOT/'codex_rollbacks'/('identity-quality-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    backup.mkdir()
    manifest=[]
    for target,before,after in changes:
        for suffix,data in [('before',before),('after',after)]:
            (backup/(target.name+'.'+suffix)).write_bytes(data)
        manifest.append(dict(target=str(target),name=target.name,before=hashlib.sha256(before).hexdigest(),after=hashlib.sha256(after).hexdigest()))
    (backup/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    (backup/'rollback.py').write_text('''from pathlib import Path
import hashlib,json,os
b=Path(__file__).parent;items=json.loads((b/'manifest.json').read_text())
for m in items:
 p=Path(m['target']);assert hashlib.sha256(p.read_bytes()).hexdigest() in (m['before'],m['after']), 'Source drift'
 assert hashlib.sha256((b/(m['name']+'.before')).read_bytes()).hexdigest()==m['before']
for m in items:
 p=Path(m['target']);t=p.with_suffix('.restore-tmp');t.write_bytes((b/(m['name']+'.before')).read_bytes());os.replace(t,p)
print('Restored source; activate only during backend idle maintenance.')
''',encoding='utf-8')
    print(json.dumps({'backup':str(backup),'staged':True,'activated':False}))

if __name__=='__main__':main()
