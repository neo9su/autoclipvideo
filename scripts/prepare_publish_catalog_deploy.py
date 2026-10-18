"""Drift-checked multi-product matching endpoint deployment."""
import ast,inspect
from pathlib import Path
from prepare_2k_deploy import raw_replacements
from prepare_remote_audio_deploy import build as backup_runner


def endpoint(source):
    node=next(n for n in ast.walk(ast.parse(source)) if isinstance(n,ast.AsyncFunctionDef) and n.name=='match_group_product')
    return '\n'.join(source.splitlines()[node.lineno-1:node.end_lineno])


def build():
    root=Path(__file__).parents[1]
    new=endpoint((root/'backend/main.py').read_text());module=(root/'backend/publish_catalog_match.py').read_text()
    setup='from pathlib import Path\nimport ast,difflib\n'+inspect.getsource(endpoint)+'\n'+inspect.getsource(raw_replacements)+'\nNEW_ENDPOINT='+repr(new)+'\nMODULE='+repr(module)+'\n'
    setup+=r'''
p=Path(r'C:\Users\neo\douyin_backend\backend\main.py');raw=p.read_bytes().decode('utf-8');old=endpoint(raw.replace('\r\n','\n'))
assert '"products": matched' not in old, 'Already patched'
text=raw.replace('\r\n','\n').replace(old,NEW_ENDPOINT)
mod=p.parent/'publish_catalog_match.py';assert not mod.exists(), 'Module drift'
mod.write_bytes(b'# pending catalogue match deployment\n')
PLAN=[(str(p),raw_replacements(raw,text)),(str(mod),[('# pending catalogue match deployment\n',MODULE)])]
'''
    return setup+backup_runner().split('\n',1)[1].replace('remote-audio-','publish-catalog-').replace("old=old.replace('\\n',newline);new=new.replace('\\n',newline)",'pass').replace('Code restored; restart backend and GPU only when idle. No database changed.','Code restored; restart only backend. No database changed.')


if __name__=='__main__':print(build())
