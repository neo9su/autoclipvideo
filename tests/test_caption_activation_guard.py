import sqlite3
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).parents[1]/'scripts'))
from activate_original_caption_sync import assert_idle


@pytest.mark.parametrize('busy', ['publish', 'clip', 'variant', 'director', None])
def test_activation_refuses_active_work(busy):
    db = sqlite3.connect(':memory:')
    db.execute('create table publish_tasks(status text)')
    db.execute('create table recordings(local_deleted integer, clipped integer)')
    db.execute('create table clip_groups(realistic_status integer, conservative_status integer, director_status integer, creative_status integer)')
    if busy == 'publish': db.execute("insert into publish_tasks values('publishing')")
    if busy == 'clip': db.execute('insert into recordings values(0,1)')
    if busy == 'variant': db.execute('insert into clip_groups values(2,1,0,0)')
    if busy == 'director': db.execute('insert into clip_groups values(2,2,1,0)')
    if busy:
        with pytest.raises(RuntimeError, match='no source files or processes changed'):
            assert_idle(db)
    else: assert_idle(db)
    db.close()
