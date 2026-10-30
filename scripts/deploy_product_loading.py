"""Activate a pre-uploaded frontend asset; no service restart or publishing call."""
from pathlib import Path
import datetime
import hashlib
import json
import os
import sqlite3
import urllib.request

ROOT=Path(r'C:\Users\neo\douyin_backend')
OLD_ASSET='index-publish-notice-d957372b5ab1.js'
OLD_SHA='d957372b5ab16a483ab4800b086434ee2e88cc2e21ed2b4b9c26f095510a7ed3'


def main(asset_name, expected_sha):
    assert asset_name=='index-product-loading-'+expected_sha[:12]+'.js'
    dist=ROOT/'frontend'/'dist';index=dist/'index.html';asset=dist/'assets'/asset_name
    staged=asset.with_suffix('.stage')
    old=index.read_bytes();text=old.decode('utf-8')
    before_url='/assets/'+OLD_ASSET;after_url='/assets/'+asset_name
    assert text.count(before_url)==1, 'Frontend entry drift; no deployment'
    assert hashlib.sha256((dist/'assets'/OLD_ASSET).read_bytes()).hexdigest()==OLD_SHA
    assert staged.exists() and hashlib.sha256(staged.read_bytes()).hexdigest()==expected_sha
    assert not asset.exists(), 'Asset already deployed; inspect first'
    new=text.replace(before_url,after_url).encode('utf-8')
    backup=ROOT/'codex_rollbacks'/('product-loading-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    backup.mkdir();(backup/'index.before').write_bytes(old)
    with sqlite3.connect(ROOT/'douyin.db') as db:
        count=db.execute('select count(*) from publish_tasks').fetchone()[0]
    manifest=dict(index=str(index),asset=str(asset),old_asset=str(dist/'assets'/OLD_ASSET),
                  before=hashlib.sha256(old).hexdigest(),after=hashlib.sha256(new).hexdigest(),
                  asset_sha=expected_sha,old_asset_sha=OLD_SHA,publish_tasks_before=count)
    (backup/'manifest.json').write_text(json.dumps(manifest,indent=2))
    (backup/'rollback.py').write_text('''from pathlib import Path
import json,hashlib,os
b=Path(__file__).parent;m=json.loads((b/'manifest.json').read_text());index=Path(m['index']);asset=Path(m['asset'])
assert hashlib.sha256(index.read_bytes()).hexdigest() in (m['before'],m['after']), 'HTML drift; stop'
old=(b/'index.before').read_bytes();assert hashlib.sha256(old).hexdigest()==m['before']
assert hashlib.sha256(Path(m['old_asset']).read_bytes()).hexdigest()==m['old_asset_sha']
if asset.exists():assert hashlib.sha256(asset.read_bytes()).hexdigest()==m['asset_sha']
t=index.with_suffix('.rollback.tmp');t.write_bytes(old);os.replace(t,index)
# Keep both immutable assets for already-open browser tabs.
print('Frontend entry restored. Refresh browser. Backend/database/media untouched.')
''')
    assert index.read_bytes()==old
    os.replace(staged,asset)
    temp=index.with_suffix('.codex.tmp');temp.write_bytes(new);os.replace(temp,index)
    try:
        with urllib.request.urlopen('http://127.0.0.1:8899/',timeout=15) as response:
            html=response.read().decode('utf-8');assert after_url in html
        with urllib.request.urlopen('http://127.0.0.1:8899'+after_url,timeout=15) as response:
            assert hashlib.sha256(response.read()).hexdigest()==expected_sha
        with sqlite3.connect(ROOT/'douyin.db') as db:
            after_count=db.execute('select count(*) from publish_tasks').fetchone()[0]
        result=dict(backup=str(backup),asset=after_url,asset_sha=expected_sha,frontend_http_verified=True,
                    publish_tasks_before=count,publish_tasks_after=after_count,no_publish_call=True,restart=False)
        (backup/'verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
    except Exception:
        # Revert only our just-written entry, without deleting either asset.
        if hashlib.sha256(index.read_bytes()).hexdigest()==manifest['after']:
            temp=index.with_suffix('.rollback.tmp');temp.write_bytes(old);os.replace(temp,index)
        raise


if __name__=='__main__':
    import sys
    main(*sys.argv[1:])
