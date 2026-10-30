"""Stage the caption repair with backups; activate only while no work is active."""
from pathlib import Path
import ast
import datetime
import hashlib
import json
import os
import sqlite3
import sys

ROOT = Path(r'C:\Users\neo\douyin_backend')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def patch_variant_namespace(source):
    tree = ast.parse(source)
    n = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_run_variant_pipeline')
    text = ast.get_source_segment(source, n)
    assert text.count('room_name=safe_room,') == 1, 'Variant namespace source drift'
    text = text.replace('room_name=safe_room,', 'room_name=f"publish-variant-{version}-{group_id}",')
    lines = source.splitlines(keepends=True)
    lines[n.lineno - 1:n.end_lineno] = [text + '\n']
    result = ''.join(lines)
    compile(result, '<variant-namespace>', 'exec')
    return result


def main(stage):
    sys.path.insert(0, str(stage))
    from patch_original_caption_sync import patch
    changes = []
    for name, transform in [('editor.py', patch), ('transcribe.py', patch_variant_namespace)]:
        target = ROOT/'backend'/name
        before = target.read_bytes()
        source = before.decode('utf-8-sig').replace('\r\n', '\n')
        after = transform(source).encode('utf-8')
        compile(after, str(target), 'exec')
        changes.append((target, before, after))
    backup = ROOT/'codex_rollbacks'/('original-caption-sync-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    backup.mkdir()
    manifest = []
    for target, before, after in changes:
        (backup/(target.name+'.before')).write_bytes(before)
        (backup/(target.name+'.after')).write_bytes(after)
        manifest.append(dict(target=str(target), name=target.name, before=sha(before), after=sha(after)))
    (backup/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    (backup/'rollback.py').write_text('''from pathlib import Path
import hashlib,json,os
b=Path(__file__).parent;items=json.loads((b/'manifest.json').read_text())
for m in items:
 p=Path(m['target']);assert hashlib.sha256(p.read_bytes()).hexdigest() in (m['before'],m['after']),'Source drift; stop'
 assert hashlib.sha256((b/(m['name']+'.before')).read_bytes()).hexdigest()==m['before']
for m in items:
 p=Path(m['target']);t=p.with_suffix('.restore-tmp');t.write_bytes((b/(m['name']+'.before')).read_bytes());os.replace(t,p)
print('Original source restored. Restart the interactive backend only when idle; database/media untouched.')
''', encoding='utf-8')
    # Only stage the change. Running publication/recording workers keep their code.
    # Activation must re-check active jobs and original hashes before replacing files.
    print(json.dumps(dict(backup=str(backup), staged=True, activated=False,
                          changes=manifest, database_changed=False, media_changed=False)))


if __name__ == '__main__':
    main(Path(sys.argv[1]))
