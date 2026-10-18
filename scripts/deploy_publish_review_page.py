"""Deploy confirmation HTML through existing static files without interrupting a live page."""
from pathlib import Path
import ast


def build():
    root=Path(__file__).parents[1];source=(root/'backend/publish_review.py').read_text()
    html=ast.literal_eval(next(n.value for n in ast.parse(source).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='REVIEW_HTML' for t in n.targets)))
    return 'SOURCE='+repr(source)+'\nHTML='+repr(html)+'\n'+r'''
from pathlib import Path
import hashlib,json,datetime,os
root=Path(r'C:\Users\neo\douyin_backend');module=root/'backend'/'publish_review.py';index=root/'frontend'/'dist'/'index.html';page=index.parent/'publish-review.html'
assert hashlib.sha256(module.read_bytes()).hexdigest()=='ebbc178f03a21dceac68ff4be1aebbcf9e9bb19262e5eed69253639e211e2678', 'Review module drift'
assert not page.exists(),'Static review page already exists'
old=index.read_bytes();text=old.decode('utf-8');anchor='id="publish-review-entry" href="/publish-review"';assert text.count(anchor)==1
new=text.replace(anchor,'id="publish-review-entry" href="/frontend/publish-review.html"').encode('utf-8')
compile(SOURCE,str(module),'exec')
changes=[(module,module.read_bytes(),SOURCE.encode('utf-8')),(page,None,HTML.encode('utf-8')),(index,old,new)]
b=root/'codex_rollbacks'/('publish-review-state-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));b.mkdir();manifest=[]
for i,(p,old,new) in enumerate(changes):
 if old is not None:(b/str(i)).write_bytes(old)
 manifest.append({'target':str(p),'backup':str(i),'before':hashlib.sha256(old).hexdigest() if old is not None else None,'after':hashlib.sha256(new).hexdigest()})
(b/'manifest.json').write_text(json.dumps(manifest,indent=2))
(b/'rollback.py').write_text("""from pathlib import Path
import hashlib,json,os
b=Path(__file__).parent;items=json.loads((b/'manifest.json').read_text())
for m in items:
 p=Path(m['target']);assert p.exists() and hashlib.sha256(p.read_bytes()).hexdigest()==m['after'], 'Source drift'
for m in reversed(items):
 p=Path(m['target'])
 if m['before'] is None:p.unlink()
 else:
  t=p.with_suffix('.rollback.tmp');t.write_bytes((b/m['backup']).read_bytes());os.replace(t,p)
print('Page/source restored. No running publishing task or database changed.')
""")
for p,old,new in changes:
 assert (p.read_bytes() if p.exists() else None)==old,'Source drift'
for p,old,new in changes:
 t=p.with_suffix('.review.tmp');t.write_bytes(new);os.replace(t,p)
print(json.dumps({'backup':str(b),'page':'/frontend/publish-review.html','backend_restarted':False,'legacy_route_source_updated':True}))
'''


if __name__=='__main__':print(build())
