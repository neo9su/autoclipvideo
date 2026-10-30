import importlib.util
from pathlib import Path
import sqlite3
import pytest
p=Path(__file__).parents[1]/'scripts/patch_pipeline_stats.py'
spec=importlib.util.spec_from_file_location('patch',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def test_deleted_and_unfinished_are_not_pending():
    source='''async def get_stats():
    sql = "SELECT SUM(CASE WHEN transcribed = 2 AND clipped = 0 THEN 1 ELSE 0 END) FROM recordings"
'''
    patched=m.patch(source)
    import ast
    sql=ast.parse(patched).body[0].body[0].value.value
    db=sqlite3.connect(':memory:')
    db.execute('CREATE TABLE recordings(transcribed,clipped,local_deleted,end_time)')
    db.executemany('INSERT INTO recordings VALUES(?,?,?,?)',[(2,0,1,'done'),(2,0,0,None),(2,0,0,'done'),(2,2,0,'done')])
    assert db.execute(sql).fetchone()[0]==1
    with pytest.raises(RuntimeError):m.patch(patched)
