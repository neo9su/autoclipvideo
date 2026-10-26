import importlib.util
import sqlite3

spec = importlib.util.spec_from_file_location('cleanup', 'scripts/dismiss_retired_job_errors.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def test_cleanup_and_guarded_restore(tmp_path):
    db, archive = tmp_path/'test.db', tmp_path/'backup.json'
    with sqlite3.connect(db) as c:
        c.execute('CREATE TABLE recordings(id INTEGER PRIMARY KEY, local_deleted INTEGER, clipped INTEGER, transcribed INTEGER, clip_error TEXT, transcribe_error TEXT, skip_reason TEXT)')
        c.executemany('INSERT INTO recordings VALUES(?,?,?,?,?,?,?)', [
            (1, 1, -1, -1, 'missing', 'missing', None),
            (2, 0, -1, 2, 'temporary', None, None),
            (3, 1, -1, 1, 'old', None, None),
            (4, 1, 2, 2, None, None, None)])
    assert m.run(db, archive)['dismissed_records'] == 1
    with sqlite3.connect(db) as c:
        assert c.execute('SELECT count(*) FROM recordings').fetchone()[0] == 4
        assert c.execute('SELECT skip_reason FROM recordings WHERE id=2').fetchone()[0] is None
        c.execute('UPDATE recordings SET clipped=2 WHERE id=1')
    assert m.run(db, archive, True) == {'restored': 0, 'skipped': 1}
    with sqlite3.connect(db) as c:
        c.execute('UPDATE recordings SET clipped=-1 WHERE id=1')
    assert m.run(db, archive, True) == {'restored': 1, 'skipped': 0}
