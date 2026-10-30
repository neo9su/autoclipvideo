import sqlite3
import pytest
from backend.product_link_edit import edit_link,restore_link,validate_url


def setup(tmp_path):
    db=tmp_path/'db';j=tmp_path/'journals'
    with sqlite3.connect(db) as c:
        c.execute('CREATE TABLE products(id PRIMARY KEY,product_name,product_id,product_url)')
        c.execute('CREATE TABLE publish_tasks(id,status)')
        c.executemany('INSERT INTO products VALUES(?,?,?,?)',[(1,'same','dom_a',''),(2,'same','dom_b','https://example.invalid/b')])
    return db,j


def test_edit_duplicate_name_clear_undo_and_idempotence(tmp_path):
    db,j=setup(tmp_path);a=edit_link(db,j,1,'https://example.invalid/a','')
    with sqlite3.connect(db) as c:assert c.execute('SELECT product_name,product_id FROM products WHERE id=1').fetchone()==('same','dom_a')
    assert restore_link(db,j,a['batch_id'])['restored']
    assert restore_link(db,j,a['batch_id'])['restored']
    b=edit_link(db,j,2,'','https://example.invalid/b');assert b['product_url']==''
    assert restore_link(db,j,b['batch_id'])['restored']


def test_duplicate_stale_edit_and_undo_after_new_edit_are_rejected(tmp_path):
    db,j=setup(tmp_path)
    with pytest.raises(ValueError):edit_link(db,j,1,'https://example.invalid/b','')
    a=edit_link(db,j,1,'https://example.invalid/a','')
    with pytest.raises(ValueError):edit_link(db,j,1,'https://example.invalid/c','')
    edit_link(db,j,1,'https://example.invalid/c','https://example.invalid/a')
    with pytest.raises(ValueError):restore_link(db,j,a['batch_id'])


def test_publishing_and_bad_urls_cannot_change_database(tmp_path):
    db,j=setup(tmp_path)
    with sqlite3.connect(db) as c:c.execute("INSERT INTO publish_tasks VALUES(1,'publishing')")
    with pytest.raises(ValueError):edit_link(db,j,1,'https://example.invalid/a','')
    for value in ('javascript:alert(1)','https://user:password@example.invalid/a','https://bad host/a','https://example.invalid:bad/a'):
        with pytest.raises(ValueError):validate_url(value)
    assert validate_url('  ')==''


def test_prepared_journal_recovers_after_commit_and_noop_creates_no_edit(tmp_path):
    import json
    db,j=setup(tmp_path)
    assert not edit_link(db,j,1,'','')['changed']
    assert not list(j.glob('*.json'))
    result=edit_link(db,j,1,'https://example.invalid/a','')
    p=j/(result['batch_id']+'.json');data=json.loads(p.read_text());data['state']='prepared';p.write_text(json.dumps(data))
    assert restore_link(db,j,result['batch_id'])['restored']


def test_undo_does_not_reintroduce_a_link_reused_by_other_product(tmp_path):
    db,j=setup(tmp_path)
    cleared=edit_link(db,j,2,'','https://example.invalid/b')
    edit_link(db,j,1,'https://example.invalid/b','')
    with pytest.raises(ValueError):restore_link(db,j,cleared['batch_id'])
