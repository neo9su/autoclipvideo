"""Run the deployed pipeline against a private SQLite snapshot, never publishing."""
import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import sys
import traceback

ROOT = Path(sys.argv[1]).resolve()
BACKEND = Path(r'C:\Users\neo\douyin_backend\backend')
PRODUCTION = BACKEND.parent / 'douyin.db'
SNAPSHOT = ROOT / 'test.db'
GROUP = 5258
PRODUCT = '740'


def save(name, data):
    (ROOT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


async def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    assert not SNAPSHOT.exists(), 'Never reuse an in-flight test database'
    with sqlite3.connect(PRODUCTION) as source, sqlite3.connect(SNAPSHOT) as dest:
        source.backup(dest)
        source.row_factory = sqlite3.Row
        save('production-group-before.json', dict(source.execute('SELECT * FROM clip_groups WHERE id=?', (GROUP,)).fetchone()))
    save('manifest.json', {'group_id': GROUP, 'catalogue_id': PRODUCT, 'database': str(SNAPSHOT),
                           'production_database': str(PRODUCTION), 'publish': False,
                           'snapshot_sha256': hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest()})
    os.environ['DOUYIN_DB_PATH'] = str(SNAPSHOT)
    sys.path.insert(0, str(BACKEND))
    import db
    db.DB_PATH = str(SNAPSHOT)
    import voice_director
    voice_director._DB_PATH = str(SNAPSHOT)
    import api_v2 as api
    # Some legacy modules capture their default database path at import time.
    # Redirect only database-path constants, never monkeypatch pipeline decisions.
    for module in list(sys.modules.values()):
        if not module or not str(getattr(module, '__file__', '')).startswith(str(BACKEND)):
            continue
        for attr in ('DB_PATH', '_DB_PATH'):
            if hasattr(module, attr):
                value = getattr(module, attr)
                if isinstance(value, str) and value.lower().endswith(('douyin.db', 'test.db')):
                    setattr(module, attr, str(SNAPSHOT))
    api.voice_director._output_dir = str(ROOT / 'voice')
    (ROOT / 'voice').mkdir()
    from qianchuan_matcher import load_group_context, score_product_match
    context = await load_group_context(str(SNAPSHOT), GROUP, PRODUCT)
    match = score_product_match(context, product_id=PRODUCT, threshold=0.58)
    save('product-match.json', match)
    assert match['ok'] and str(match['product']['id']) == PRODUCT, 'Pinned product validation failed'
    from qianchuan_script import generate_qianchuan_script
    script = generate_qianchuan_script(context['group'], product_context=match['product'], target_duration=45, selling_points=[])
    script['preview_mode'] = True
    save('script.json', script)
    with sqlite3.connect(SNAPSHOT) as con:
        con.execute('UPDATE clip_groups SET qianchuan_status=1,qianchuan_error=NULL,qianchuan_preview_video=NULL,qianchuan_preview_review=NULL,qianchuan_script=? WHERE id=?', (json.dumps(script, ensure_ascii=False), GROUP))
        con.commit()
    logging.info('Starting isolated production pipeline')
    await api._qianchuan_generate_bg(GROUP, script)
    with sqlite3.connect(SNAPSHOT) as con:
        con.row_factory = sqlite3.Row
        result = dict(con.execute('SELECT qianchuan_status,qianchuan_error,qianchuan_preview_video,qianchuan_preview_review,qianchuan_segments,qianchuan_job_id FROM clip_groups WHERE id=?', (GROUP,)).fetchone())
    with sqlite3.connect(PRODUCTION) as con:
        con.row_factory = sqlite3.Row
        after = dict(con.execute('SELECT * FROM clip_groups WHERE id=?', (GROUP,)).fetchone())
    save('production-group-after.json', after)
    before = json.loads((ROOT / 'production-group-before.json').read_text(encoding='utf-8'))
    result['production_qianchuan_fields_unchanged'] = all(after[k] == before[k] for k in before if k.startswith('qianchuan'))
    save('result.json', result)
    logging.info('Finished isolated pipeline: status=%s error=%s', result['qianchuan_status'], result['qianchuan_error'])


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    try:
        asyncio.run(main())
    except Exception:
        ROOT.mkdir(parents=True, exist_ok=True)
        save('failure.json', {'traceback': traceback.format_exc()})
        raise
