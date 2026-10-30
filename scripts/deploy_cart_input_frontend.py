from pathlib import Path
import sys,hashlib,json,datetime,os,urllib.request
ROOT=Path(r'C:\Users\neo\douyin_backend')
sys.path.insert(0,str(ROOT/'codex_operations/cart-limit-ten-20261030'))
from prepare_frontend_asset_deploy import build
old='index-cart-limit-ten-9bd448513277.js';sha='9bd448513277aa67b84c50c5bf614922cacfe3745d7f4f08d73b0e8917c60598'
dist=ROOT/'frontend/dist';assets=dist/'assets';raw=(assets/old).read_bytes();assert hashlib.sha256(raw).hexdigest()==sha
s=raw.decode()
for before,after in [('failed:`失败`','waiting_input:`等待补充商品`,failed:`失败`'),('failed:`badge-red`','waiting_input:`badge-yellow`,failed:`badge-red`')]:
 assert s.count(before)==1;s=s.replace(before,after)
s+='\nimport("/publish-cart-input.js");\n'
data=s.encode();digest=hashlib.sha256(data).hexdigest();name='index-cart-input-'+digest[:12]+'.js';(assets/name).with_suffix('.stage').write_bytes(data)
ns={};exec(build(old,sha,'index-cart-input-','cart-input-frontend-'),ns);ns['main'](name,digest)
p=dist/'publish-review.html';before=p.read_bytes();assert b'/publish-cart-input.js' not in before
after=before+b'\n<script src="/publish-cart-input.js" defer></script>\n'
b=ROOT/'codex_rollbacks'/('cart-input-review-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));b.mkdir();(b/'review.before').write_bytes(before)
(b/'rollback.py').write_text('from pathlib import Path\np=Path('+repr(str(p))+')\np.write_bytes((Path(__file__).parent/"review.before").read_bytes())\n')
t=p.with_suffix('.cart-tmp');t.write_bytes(after);os.replace(t,p)
for path in ['/publish-cart-input','/publish-cart-input.js','/api/publish-cart-input']:
 with urllib.request.urlopen('http://127.0.0.1:8899'+path,timeout=15) as r:assert r.status==200
print(json.dumps({'input_routes_verified':True,'review_backup':str(b)}))
