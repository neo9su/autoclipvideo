"""Conditional, journaled edits of stored URLs; names and platform IDs stay intact."""
import json
from pathlib import Path
import sqlite3
import uuid
from urllib.parse import urlsplit


def validate_url(value):
    value=str(value or '').strip()
    if not value:return ''
    try:
        u=urlsplit(value)
        # Access port for validation, while allowing its ordinary absence.
        port=u.port
        valid=(len(value)<=2000 and not any(c.isspace() for c in value) and u.scheme in ('https','http')
               and bool(u.hostname) and not u.username and not u.password)
    except ValueError:valid=False
    if not valid:raise ValueError('请输入完整的http或https商品链接，也可以留空')
    return value


def _write(path, data):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)


def edit_link(database, journals, product_id, value, expected):
    value=validate_url(value);root=Path(journals);root.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(database,timeout=30) as con:
        con.row_factory=sqlite3.Row;con.execute('BEGIN IMMEDIATE')
        row=con.execute('SELECT * FROM products WHERE id=?',(product_id,)).fetchone()
        if row is None:raise ValueError('商品不存在')
        before=row['product_url'] or ''
        if before!=expected:raise ValueError('链接已被其他操作修改，请刷新后重试')
        if before==value:return {'id':product_id,'product_url':value,'changed':False}
        if con.execute("SELECT count(*) FROM publish_tasks WHERE status='publishing'").fetchone()[0]:
            raise ValueError('正在发布，请等待发布完成后修改链接')
        if value and con.execute("SELECT id FROM products WHERE trim(coalesce(product_url,''))=? AND id<>?",(value,product_id)).fetchone():
            raise ValueError('此链接已存在于其他商品中，同名不同链接可正常保存')
        batch=uuid.uuid4().hex
        journal={'batch_id':batch,'product_id':product_id,'before':before,'after':value,'state':'prepared'}
        path=root/(batch+'.json');_write(path,journal)
        con.execute('UPDATE products SET product_url=? WHERE id=?',(value,product_id));con.commit()
        journal['state']='applied';_write(path,journal)
        return {'id':product_id,'product_url':value,'changed':True,'batch_id':batch}


def restore_link(database,journals,batch):
    if len(batch)!=32 or any(c not in '0123456789abcdef' for c in batch):raise ValueError('无效回退记录')
    path=Path(journals)/(batch+'.json')
    if not path.is_file():raise ValueError('回退记录不存在')
    j=json.loads(path.read_text(encoding='utf-8'))
    with sqlite3.connect(database,timeout=30) as con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute('SELECT product_url FROM products WHERE id=?',(j['product_id'],)).fetchone()
        if row is None:raise ValueError('商品已不存在')
        current=row[0] or ''
        if current==j['before']:
            j['state']='restored';_write(path,j)
            return {'restored':True,'product_id':j['product_id']}
        if current!=j['after']:raise ValueError('链接已再次变更，不能覆盖后续编辑')
        if con.execute("SELECT count(*) FROM publish_tasks WHERE status='publishing'").fetchone()[0]:raise ValueError('正在发布，请稍后回退')
        if j['before'] and con.execute("SELECT id FROM products WHERE trim(coalesce(product_url,''))=? AND id<>?",(j['before'],j['product_id'])).fetchone():raise ValueError('原链接已用于其他商品，不能重复恢复')
        con.execute('UPDATE products SET product_url=? WHERE id=?',(j['before'],j['product_id']));con.commit()
        j['state']='restored';_write(path,j)
        return {'restored':True,'product_id':j['product_id']}
