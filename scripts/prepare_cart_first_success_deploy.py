"""Stage first-success cart policy only; backup and compile before mutation."""
from pathlib import Path
from prepare_remote_audio_deploy import build as backup_runner


def build():
    new=(Path(__file__).parents[1]/'backend/publish_cart_flow.py').read_text()
    return 'NEW_SOURCE='+repr(new)+'\n'+r'''
from pathlib import Path
import hashlib
p=Path(r'C:\Users\neo\douyin_backend\backend\publish_cart_flow.py');raw=p.read_bytes()
assert hashlib.sha256(raw).hexdigest()=='cf82e8b9b5f7da60c3cf2545d7ba20c2e09a21701d331fafafa91e77f763e043','Source drift'
PLAN=[(str(p),[(raw.decode('utf-8'),NEW_SOURCE)])]
'''+backup_runner().split('\n',1)[1].replace('remote-audio-','cart-first-success-').replace('Code restored; restart backend and GPU only when idle. No database changed.','Code restored; restart only backend. No database changed.')


if __name__=='__main__':print(build())
