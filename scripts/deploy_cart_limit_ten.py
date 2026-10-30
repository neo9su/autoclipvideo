"""Stage backend guards; activate the immutable frontend after backend maintenance."""
from pathlib import Path
import datetime,hashlib,json,sys
from prepare_frontend_asset_deploy import build
ROOT=Path(r'C:\Users\neo\douyin_backend')
OLD='index-product-ids-b5c050e086c1.js'
SHA='b5c050e086c144d0621d48eb2208c521ed6309576794fd463be828e63e5ba93b'


def replace(source,old,new,count=1):
    assert source.count(old)==count, 'Cart limit source drift: '+old
    return source.replace(old,new)


def stage():
    changes=[]
    for name,old,new in [('publisher_douyin.py','len(product_ids) > 5','len(product_ids) > 10'),('publish_product_links.py','len(links)>5','len(links)>10')]:
        target=ROOT/'backend'/name;before=target.read_bytes()
        after=replace(before.decode('utf-8-sig'),old,new)
        after=replace(after,'最多挂车5个','最多挂车10个').encode('utf-8');compile(after,str(target),'exec')
        changes.append((target,before,after))
    backup=ROOT/'codex_rollbacks'/('cart-limit-ten-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));backup.mkdir()
    manifest=[]
    for p,b,a in changes:
        (backup/(p.name+'.before')).write_bytes(b);(backup/(p.name+'.after')).write_bytes(a)
        manifest.append(dict(target=str(p),name=p.name,before=hashlib.sha256(b).hexdigest(),after=hashlib.sha256(a).hexdigest()))
    (backup/'manifest.json').write_text(json.dumps(manifest,indent=2))
    (backup/'rollback.py').write_text('''from pathlib import Path
import hashlib,json,os
b=Path(__file__).parent;items=json.loads((b/'manifest.json').read_text())
for m in items:
 assert hashlib.sha256(Path(m['target']).read_bytes()).hexdigest() in (m['before'],m['after'])
 assert hashlib.sha256((b/(m['name']+'.before')).read_bytes()).hexdigest()==m['before']
for m in items:
 p=Path(m['target']);t=p.with_suffix('.restore-tmp');t.write_bytes((b/(m['name']+'.before')).read_bytes());os.replace(t,p)
print('Sources restored; restart interactive backend when idle.')
''')
    print(json.dumps({'backup':str(backup),'activated':False}))


def frontend():
    assets=ROOT/'frontend/dist/assets';raw=(assets/OLD).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==SHA
    s=raw.decode('utf-8')
    for old,new,count in [('sharedCart.product_ids.length > 5','sharedCart.product_ids.length > 10',1),('最多选择5件共同挂车商品','最多选择10件共同挂车商品',1),('a.length>5','a.length>10',2),('平台最多挂5件','本系统最多选择10件',1)]:s=replace(s,old,new,count)
    data=s.encode('utf-8');digest=hashlib.sha256(data).hexdigest();name='index-cart-limit-ten-'+digest[:12]+'.js'
    (assets/name).with_suffix('.stage').write_bytes(data)
    ns={'__name__':'cart_limit_deploy'};exec(build(OLD,SHA,'index-cart-limit-ten-','cart-limit-frontend-'),ns);ns['main'](name,digest)

if __name__=='__main__':
    {'stage':stage,'frontend':frontend}[sys.argv[1]]()
