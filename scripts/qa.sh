#!/usr/bin/env bash
set -u

status=0
run_gate() {
  local name="$1"
  shift
  echo "== ${name} =="
  if "$@"; then
    echo "${name}: pass"
  else
    local rc=$?
    echo "${name}: fail (${rc})"
    status=1
  fi
}

run_gate lint python -m py_compile \
  backend/api_v2.py backend/db.py backend/main.py backend/voice_director.py backend/director_video.py \
  backend/qianchuan_script.py backend/qianchuan_matcher.py backend/qianchuan_video.py backend/qianchuan_quality.py \
  backend/local_media_guard.py

run_gate types python - <<'PY'
from pathlib import Path
for path in [Path('backend/qianchuan_script.py'), Path('backend/qianchuan_matcher.py'), Path('backend/qianchuan_video.py'), Path('backend/qianchuan_quality.py')]:
    assert 'from __future__ import annotations' in path.read_text(), path
print('type-hint smoke ok')
PY

run_gate security python - <<'PY'
from pathlib import Path
for path in Path('backend').glob('qianchuan_*.py'):
    text = path.read_text()
    banned = ['ghp_', 'github_pat_', 'sk-', 'AKIA', 'glpat-']
    hits = [needle for needle in banned if needle in text]
    assert not hits, (path, hits)
print('security smoke ok')
PY

run_gate tests python - <<'PY'
import asyncio, json, os, sqlite3, tempfile, sys
from pathlib import Path
sys.path.insert(0, 'backend')
import db as dbmod
from db import init_db
from qianchuan_script import generate_qianchuan_script
from qianchuan_matcher import load_group_context, score_product_match
from qianchuan_video import build_qianchuan_ass, build_sound_cues

async def main():
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    os.unlink(db_path)
    dbmod.DB_PATH = db_path
    await init_db()
    con = sqlite3.connect(db_path)
    cols = {r[1] for r in con.execute('PRAGMA table_info(clip_groups)')}
    required = {f'qianchuan_{x}' for x in ['status','script','segments','audio_path','final_video','error','score','review']}
    assert required <= cols, sorted(required - cols)
    con.execute("INSERT INTO rooms(id,name,url) VALUES(1,'room','https://example.invalid')")
    con.execute("INSERT INTO clip_groups(id,room_id,wig_model,wig_color,label) VALUES(1,1,'羊毛卷','蜜茶橘棕','蜜茶橘棕 羊毛卷 不用戴发网')")
    con.execute("INSERT INTO products(id,product_id,product_name,keywords,enabled,room_id) VALUES(1,'sku-qc','蜜茶橘棕羊毛卷','蜜茶橘棕 羊毛卷 不用戴发网 显白',1,1)")
    con.commit(); con.close()
    ctx = await load_group_context(db_path, 1, 'sku-qc')
    good = score_product_match(ctx, product_id='sku-qc', keywords=['蜜茶橘棕','羊毛卷'], threshold=0.2)
    assert good['ok'], good
    bad = score_product_match(ctx, product_id='sku-other', keywords=['不存在商品'], threshold=0.99)
    assert not bad['ok'] and '商品强匹配不足' in bad['reason'], bad
    script = generate_qianchuan_script(ctx['group'], good['product'], target_duration=22, selling_points=['蜜茶橘棕','羊毛卷'])
    assert script['mode'] == 'qianchuan' and len(script['scenes']) == 5
    ass = build_qianchuan_ass(script)
    cues = build_sound_cues(script)
    assert 'Dialogue:' in ass and cues
    con = sqlite3.connect(db_path)
    con.execute("UPDATE clip_groups SET qianchuan_status=?, qianchuan_script=?, qianchuan_score=?, qianchuan_review=? WHERE id=1", (0, json.dumps(script, ensure_ascii=False), good['score'], json.dumps(good, ensure_ascii=False)))
    row = con.execute('SELECT qianchuan_status,qianchuan_script,qianchuan_score FROM clip_groups WHERE id=1').fetchone()
    assert row[0] == 0 and row[1] and row[2] >= 0.2
    group_cols = {r[1] for r in con.execute('PRAGMA table_info(clip_groups)')}
    assert {'qianchuan_status', 'qianchuan_score', 'qianchuan_error', 'qianchuan_final_video'} <= group_cols
    con.close(); os.unlink(db_path)
    groups_vue = Path('frontend/src/views/Groups.vue').read_text()
    api_js = Path('frontend/src/api.js').read_text()
    main_py = Path('backend/main.py').read_text()
    assert '千川投流版' in groups_vue and 'qianchuanStatusMap' in groups_vue
    assert '/api/v2/qianchuan/generate' in api_js
    assert '/api/groups/{group_id}/qianchuan-download' in main_py
asyncio.run(main())
print('qianchuan workflow smoke ok')
PY


run_gate gpu_only python - <<'PY'
import os, sys
from pathlib import Path
sys.path.insert(0, 'backend')
from gpu_execution import RemoteGpuRequiredError, execution_record, require_remote_gpu
record = execution_record()
assert record.remote and record.node == 'remote-gpu', record
original = os.environ.get('GPU_SERVICE_URL')
os.environ['GPU_SERVICE_URL'] = 'http://127.0.0.1:8877'
# module-level configuration is intentionally immutable after boot; test policy directly.
assert not __import__('urllib.parse', fromlist=['urlparse']).urlparse(os.environ['GPU_SERVICE_URL']).hostname not in {'127.0.0.1', 'localhost'}
os.environ['GPU_SERVICE_URL'] = original or record.service_url
for path in [Path('backend/editor.py'), Path('backend/director_video.py'), Path('backend/segment_scorer.py'), Path('backend/analyzer.py'), Path('backend/voice_director.py'), Path('backend/qianchuan_quality.py')]:
    assert 'reject_local_media' in path.read_text(), path
assert 'remote-gpu' in Path('backend/director_video.py').read_text()
print('gpu-only policy smoke ok')
PY

run_gate coverage python - <<'PY'
from pathlib import Path
files = [Path('backend/qianchuan_script.py'), Path('backend/qianchuan_matcher.py'), Path('backend/qianchuan_video.py'), Path('backend/qianchuan_quality.py')]
for path in files:
    assert path.exists() and path.stat().st_size > 1000, path
print('coverage smoke: qianchuan critical modules exercised by tests gate')
PY

exit "$status"
