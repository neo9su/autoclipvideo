from pathlib import Path
import datetime,hashlib,json,sys
import patch_cart_input as patch
ROOT=Path(r'C:\Users\neo\douyin_backend')

def main(stage):
    changes=[]
    for name,fn in [('publish_scheduler.py',patch.scheduler),('publish_review.py',patch.review)]:
        p=ROOT/'backend'/name;b=p.read_bytes();a=fn(b.decode('utf-8-sig')).encode();compile(a,str(p),'exec');changes.append((p,b,a))
    module=ROOT/'backend/publish_cart_input.py';data=(stage/'publish_cart_input.py').read_bytes();compile(data,str(module),'exec')
    assert not module.exists(),'Module already exists; inspect before replacing'
    backup=ROOT/'codex_rollbacks'/('cart-input-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));backup.mkdir()
    manifest=[]
    for p,b,a in changes:
        (backup/(p.name+'.before')).write_bytes(b);(backup/(p.name+'.after')).write_bytes(a)
        manifest.append(dict(target=str(p),name=p.name,before=hashlib.sha256(b).hexdigest(),after=hashlib.sha256(a).hexdigest()))
    (backup/'manifest.json').write_text(json.dumps(manifest,indent=2))
    (backup/'publish_cart_input.py').write_bytes(data);module.write_bytes(data)
    (backup/'rollback.py').write_text('''from pathlib import Path
import json,hashlib,os
b=Path(__file__).parent
for m in json.loads((b/'manifest.json').read_text()):
 p=Path(m['target']);assert hashlib.sha256(p.read_bytes()).hexdigest() in (m['before'],m['after'])
 a=(b/(m['name']+'.before')).read_bytes();assert hashlib.sha256(a).hexdigest()==m['before']
 t=p.with_suffix('.restore-tmp');t.write_bytes(a);os.replace(t,p)
print('Sources restored. Restart only when idle. waiting_input tasks remain preserved.')
''')
    print(json.dumps({'backup':str(backup),'activated':False}))
if __name__=='__main__':main(Path(sys.argv[1]))
