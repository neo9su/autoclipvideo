"""Patch the deployed legacy clip admission guard without replacing service code."""
from pathlib import Path
import datetime
import hashlib
import json
import os


OLD = '''    if free_gb < CLIP_MIN_FREE_GB:
        logger.warning(f"Low disk space: {free_gb:.1f}GB free, cannot start clip job")
        _clip_jobs.pop(job_id, None)
        raise HTTPException('''
NEW = OLD.replace('        _clip_jobs.pop(job_id, None)\n', '')


def patch_source(source):
    # The job is created after admission, so there is nothing to remove here.
    if source.count(OLD) != 1:
        raise RuntimeError("Legacy disk guard differs; refusing patch")
    patched = source.replace(OLD, NEW)
    compile(patched, "gpu_service/main.py", "exec")
    return patched


def main():
    root = Path(r"C:\Users\neo\douyin_backend")
    targets = [Path(r"C:\Users\neo\douyin_processor\gpu_service\main.py"),
               root / "gpu_service" / "main.py"]
    prepared = [(p, p.read_bytes()) for p in targets]
    changes = [(p, old, patch_source(old.decode("utf-8")).encode("utf-8"))
               for p, old in prepared]
    backup = root / "codex_rollbacks" / ("clip-low-disk-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    backup.mkdir(parents=True)
    manifest = []
    for i, (p, old, new) in enumerate(changes):
        name = f"{i}.before"
        (backup / name).write_bytes(old)
        manifest.append(dict(target=str(p), backup=name,
                             before=hashlib.sha256(old).hexdigest(),
                             after=hashlib.sha256(new).hexdigest()))
    (backup / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (backup / "rollback.py").write_text('''from pathlib import Path
import hashlib,json,os
b=Path(__file__).parent
items=json.loads((b/'manifest.json').read_text())
for m in items:
    assert hashlib.sha256(Path(m['target']).read_bytes()).hexdigest() in (m['before'],m['after']), 'Source drift; refusing rollback'
    assert hashlib.sha256((b/m['backup']).read_bytes()).hexdigest()==m['before']
for m in items:
    p=Path(m['target']);t=p.with_suffix('.rollback.tmp')
    t.write_bytes((b/m['backup']).read_bytes());os.replace(t,p)
print('Code restored; restart GPU service only when idle. No database changed.')
''', encoding="utf-8")
    for p, old, new in changes:
        if p.read_bytes() != old:
            raise RuntimeError("Source drift during backup")
    for p, old, new in changes:
        temp = p.with_suffix(".codex.tmp")
        temp.write_bytes(new)
        os.replace(temp, p)
    print(json.dumps({"backup": str(backup), "files": manifest,
                      "runtime_restart_required": True}))


if __name__ == "__main__":
    main()
