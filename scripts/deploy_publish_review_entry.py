"""Run on 203: preserve the live frontend bundle; add a review entry only."""
from pathlib import Path
import hashlib,json,datetime,os
p=Path(r'C:\Users\neo\douyin_backend\frontend\dist\index.html')
old=p.read_bytes();s=old.decode('utf-8')
assert 'id="publish-review-entry"' not in s
anchor='<a id="publish-review-entry" href="/publish-review" target="_blank" rel="noopener" style="position:fixed;right:18px;bottom:18px;z-index:2000;padding:12px 16px;border-radius:8px;background:#ed2852;color:white;text-decoration:none;font:14px system-ui">查看发布页面 / 确认发布</a>'
assert s.count('</body>')==1
new=s.replace('</body>',anchor+'</body>').encode()
b=p.parents[2]/'codex_rollbacks'/('publish-review-entry-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));b.mkdir()
(b/'index.before').write_bytes(old)
m={'target':str(p),'before':hashlib.sha256(old).hexdigest(),'after':hashlib.sha256(new).hexdigest()};(b/'manifest.json').write_text(json.dumps(m,indent=2))
(b/'rollback.py').write_text("""from pathlib import Path
import json,hashlib,os
b=Path(__file__).parent;m=json.loads((b/'manifest.json').read_text());p=Path(m['target'])
assert hashlib.sha256(p.read_bytes()).hexdigest() in (m['before'],m['after']), 'Source drift'
t=p.with_suffix('.rollback.tmp');t.write_bytes((b/'index.before').read_bytes());os.replace(t,p)
""")
assert p.read_bytes()==old
t=p.with_suffix('.review.tmp');t.write_bytes(new);os.replace(t,p)
print(json.dumps({'backup':str(b),'manifest':m}))
