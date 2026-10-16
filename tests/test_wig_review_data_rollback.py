import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest

spec = importlib.util.spec_from_file_location('rollback_data', Path(__file__).resolve().parents[1] / 'scripts/rollback_wig_review_holds.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def database(tmp_path):
    path = tmp_path / 'live.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE clip_groups (id PRIMARY KEY,qianchuan_status,qianchuan_error,qianchuan_review)')
        saved = json.dumps({'hold_type': 'wig_identity_v1', 'previous_state': {'status': 0, 'error': 'before', 'review': 'original'}})
        db.executemany('INSERT INTO clip_groups VALUES (?,?,?,?)', [(7,-5,'held',saved),(8,2,None,'unrelated')])
    return path


def test_dry_run_and_backup_protected_scoped_restore(tmp_path):
    p = database(tmp_path)
    before = p.read_bytes()
    result = module.rollback_holds(p, [7])
    assert not result['applied'] and p.read_bytes() == before
    backup = tmp_path / 'snapshot.db'
    assert module.rollback_holds(p, [7], apply=True, backup=backup)['applied']
    with sqlite3.connect(p) as db:
        assert db.execute('SELECT * FROM clip_groups WHERE id=7').fetchone() == (7,0,'before','original')
        assert db.execute('SELECT * FROM clip_groups WHERE id=8').fetchone() == (8,2,None,'unrelated')
    with sqlite3.connect(backup) as db:
        assert db.execute('SELECT qianchuan_status FROM clip_groups WHERE id=7').fetchone()[0] == -5


def test_rollback_rejects_non_hold_before_any_mutation(tmp_path):
    p = database(tmp_path)
    before = p.read_bytes()
    with pytest.raises(ValueError): module.rollback_holds(p, [7,8], apply=True, backup=tmp_path/'backup.db')
    assert p.read_bytes() == before


def test_apply_requires_new_backup_and_does_not_overwrite_existing(tmp_path):
    p = database(tmp_path)
    with pytest.raises(ValueError): module.rollback_holds(p, [7], apply=True)
    b = tmp_path/'backup.db'; b.write_bytes(b'do not overwrite')
    with pytest.raises(FileExistsError): module.rollback_holds(p, [7], apply=True, backup=b)
    assert b.read_bytes() == b'do not overwrite'
