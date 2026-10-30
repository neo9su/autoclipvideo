import importlib.util,sqlite3
from pathlib import Path
p=Path(__file__).parents[1]/'scripts/patch_unusable_retry_sources.py'
s=importlib.util.spec_from_file_location('retry_patch',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def test_eligible_source_required():
    db=sqlite3.connect(':memory:')
    db.executescript('CREATE TABLE clip_groups(id); CREATE TABLE recordings(group_id,local_deleted,transcribed,end_time); INSERT INTO clip_groups VALUES(1),(2),(3),(4),(5);')
    db.executemany('INSERT INTO recordings VALUES(?,?,?,?)',[(1,1,2,'done'),(2,0,0,'done'),(3,0,2,None),(4,0,2,'done'),(4,1,2,'done')])
    assert db.execute('SELECT id FROM clip_groups WHERE 1=1 '+m.NEW).fetchall()==[(4,)]
