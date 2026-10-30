"""Activate a staged repair only after publication/editing work has drained."""
from pathlib import Path
import hashlib
import json
import os
import sqlite3
import subprocess
import sys

ROOT = Path(r'C:\Users\neo\douyin_backend')


def assert_idle(db):
    checks = [
        ("SELECT count(*) FROM publish_tasks WHERE status='publishing'", 'Publication active'),
        ('SELECT count(*) FROM recordings WHERE local_deleted=0 AND clipped=1', 'Editing active'),
        ('SELECT count(*) FROM clip_groups WHERE realistic_status=1 OR conservative_status=1', 'Variant rendering active'),
        ('SELECT count(*) FROM clip_groups WHERE director_status=1 OR creative_status=1', 'Other rendering active'),
    ]
    for sql, reason in checks:
        if db.execute(sql).fetchone()[0]:
            raise RuntimeError(reason + '; no source files or processes changed')


def atomic(path, data):
    temp = path.with_suffix('.caption-tmp')
    temp.write_bytes(data)
    os.replace(temp, path)


def main(backup):
    sys.path.insert(0, str(ROOT/'codex_operations/publish-groups-20261025/release-v1'))
    import backend_restart_utils as maintenance
    manifest = json.loads((backup/'manifest.json').read_text())
    for item in manifest:
        assert hashlib.sha256(Path(item['target']).read_bytes()).hexdigest() == item['before'], 'Production source drift'
        data = (backup/(item['name']+'.after')).read_bytes()
        assert hashlib.sha256(data).hexdigest() == item['after'], 'Staged source drift'
        compile(data, item['target'], 'exec')
    with sqlite3.connect(ROOT/'douyin.db') as db:
        assert_idle(db)
    plan = maintenance.backend_task_plan()
    assert plan['restart_task'] == 'DouyinBackend8899SusunInteractive'
    pids = maintenance.backend_pids()
    assert len(pids) == 1
    (backup/'task-state.json').write_text(json.dumps(plan, indent=2))
    changed = []
    applied = False
    db = sqlite3.connect(ROOT/'douyin.db', timeout=5)
    try:
        db.execute('BEGIN IMMEDIATE')
        assert_idle(db)
        maintenance.pause_backend_tasks(plan, changed)
        for pid in pids & maintenance.backend_pids():
            subprocess.run(['taskkill', '/PID', str(pid), '/F'], capture_output=True, check=True)
        assert not maintenance.backend_pids()
        for item in manifest:
            target = Path(item['target'])
            assert hashlib.sha256(target.read_bytes()).hexdigest() == item['before'], 'Source changed before activation'
        for item in manifest:
            atomic(Path(item['target']), (backup/(item['name']+'.after')).read_bytes())
        applied = True
    finally:
        if changed and not applied:
            for item in manifest:
                atomic(Path(item['target']), (backup/(item['name']+'.before')).read_bytes())
        db.rollback()
        db.close()
        if changed:
            maintenance.restore_backend_tasks(plan, changed)
    result = dict(activated=applied, gpu_restarted=False, media_changed=False, database_changed=False)
    (backup/'activation.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == '__main__':
    main(Path(sys.argv[1]))
