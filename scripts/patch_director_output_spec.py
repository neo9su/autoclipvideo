"""Run on Windows: drift-checked one-line fix with conditional code rollback."""
from pathlib import Path
import datetime
import hashlib
import json
import sqlite3


def main():
    root = Path(r"C:\Users\neo\douyin_backend")
    target = root / "backend" / "director_video.py"
    old = '"qianchuan_output_spec": config.get("qianchuan_output_spec"),'
    new = '"qianchuan_output_spec": config.get("qianchuan_output_spec") or {},'
    original = target.read_bytes()
    source = original.decode("utf-8")
    if source.count(old) != 1:
        raise RuntimeError("Unexpected source; refusing patch")
    patched = source.replace(old, new).encode("utf-8")
    compile(patched, str(target), "exec")
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = root / "codex_rollbacks" / ("director-output-spec-" + stamp)
    backup.mkdir(parents=True)
    (backup / "director_video.py.before").write_bytes(original)
    with sqlite3.connect(root / "douyin.db") as db:
        with sqlite3.connect(backup / "douyin.db.snapshot") as snapshot:
            db.backup(snapshot)
    digest = hashlib.sha256(patched).hexdigest()
    manifest = {"target": str(target), "before_sha256": hashlib.sha256(original).hexdigest(),
                "after_sha256": digest, "database_restore": "never automatic"}
    (backup / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    rollback = '''from pathlib import Path
import hashlib,json,os
b=Path(__file__).parent
m=json.loads((b/'manifest.json').read_text())
p=Path(m['target'])
assert hashlib.sha256(p.read_bytes()).hexdigest()==m['after_sha256'], 'Source changed; refusing rollback'
data=(b/'director_video.py.before').read_bytes()
assert hashlib.sha256(data).hexdigest()==m['before_sha256']
t=p.with_suffix('.rollback.tmp');t.write_bytes(data);os.replace(t,p)
print('Code restored; restart backend when idle. Database untouched.')
'''
    (backup / "rollback.py").write_text(rollback, encoding="utf-8")
    if target.read_bytes() != original:
        raise RuntimeError("Source changed during backup")
    temp = target.with_suffix(".codex.tmp")
    temp.write_bytes(patched)
    temp.replace(target)
    print(json.dumps({"backup": str(backup), "sha256": digest}))


if __name__ == "__main__":
    main()
