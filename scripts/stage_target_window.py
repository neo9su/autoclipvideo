from pathlib import Path
import json,hashlib,datetime,sys
import patch_target_window as patch
ROOT=Path(r'C:\Users\neo\douyin_backend')

def main(stage):
    changes=[]
    for name,fn in [('editor.py',patch.editor),('transcribe.py',patch.transcribe),('wig_boundary.py',patch.boundary)]:
        target=ROOT/'backend'/name;before=target.read_bytes();after=fn(before.decode('utf-8-sig')).encode('utf-8');compile(after,str(target),'exec');changes.append((target,before,after))
    module=ROOT/'backend/wig_target_window.py';data=(stage/'wig_target_window.py').read_bytes();compile(data,str(module),'exec')
    if module.exists() and module.read_bytes()!=data:raise ValueError('Existing target module differs')
    b=ROOT/'codex_rollbacks'/('target-window-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));b.mkdir()
    manifest=[]
    for target,before,after in changes:
        for suffix,content in [('before',before),('after',after)]: (b/(target.name+'.'+suffix)).write_bytes(content)
        manifest.append(dict(target=str(target),name=target.name,before=hashlib.sha256(before).hexdigest(),after=hashlib.sha256(after).hexdigest()))
    (b/'manifest.json').write_text(json.dumps(manifest,indent=2))
    (b/'wig_target_window.py').write_bytes(data);module.write_bytes(data)
    (b/'rollback.py').write_text('''from pathlib import Path
import hashlib,json,os
b=Path(__file__).parent;items=json.loads((b/'manifest.json').read_text())
for m in items:
 assert hashlib.sha256(Path(m['target']).read_bytes()).hexdigest() in (m['before'],m['after'])
 assert hashlib.sha256((b/(m['name']+'.before')).read_bytes()).hexdigest()==m['before']
for m in items:
 p=Path(m['target']);t=p.with_suffix('.restore-tmp');t.write_bytes((b/(m['name']+'.before')).read_bytes());os.replace(t,p)
print('Sources restored; idle interactive backend restart required.')
''')
    print(json.dumps({'backup':str(b),'activated':False}))
if __name__=='__main__':main(Path(sys.argv[1]))
