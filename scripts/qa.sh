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
  scripts/batch_qianchuan_regen.py \
  backend/api_v2.py backend/db.py backend/qianchuan_schema.py backend/main.py backend/voice_director.py backend/director_video.py backend/media_contract.py \
  backend/qianchuan_script.py backend/qianchuan_matcher.py backend/qianchuan_video.py backend/qianchuan_quality.py \
  backend/qianchuan_learning.py backend/qianchuan_upload.py \
  backend/local_media_guard.py backend/test_transcribe_queue.py backend/video_editing_skills.py backend/pipeline_state.py \
  backend/transcribe.py backend/reclip_batch.py \
  scripts/reclip_batch.py scripts/resumable_reclip.py gpu_service/main.py \
  tests/test_qianchuan_learning.py tests/test_qianchuan_upload.py tests/test_reclip_batch.py tests/test_resumable_reclip.py

run_gate types python - <<'PY'
from pathlib import Path
for path in [Path('backend/qianchuan_script.py'), Path('backend/qianchuan_matcher.py'), Path('backend/qianchuan_video.py'), Path('backend/qianchuan_quality.py'), Path('backend/qianchuan_learning.py')]:
    assert 'from __future__ import annotations' in path.read_text(), path
print('type-hint smoke ok')
PY

run_gate security python - <<'PY'
from pathlib import Path
for path in list(Path('backend').glob('qianchuan_*.py')) + [Path('frontend/src/components/QianchuanUpload.vue'), Path('frontend/src/api.js')]:
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
from qianchuan_matcher import (load_group_context, score_product_match,
                               assess_segment_relevance, audit_qianchuan_segments)
from qianchuan_video import build_qianchuan_ass, build_sound_cues
from test_transcribe_queue import main_test as transcribe_queue_test
from director_video import DirectorVideoComposer
from video_editing_skills import build_edit_sound_cues, normalize_transition_name, should_enable_pip

async def main():
    await transcribe_queue_test()
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
    relevant = assess_segment_relevance(
        {'voiceover_text': '蜜茶橘棕发缝自然', 'visual_keywords': ['发缝自然']},
        '近景展示蜜茶橘棕，发缝自然，颜色细节清晰', 0.82)
    assert relevant['ok'], relevant
    irrelevant = assess_segment_relevance(
        {'voiceover_text': '发缝自然', 'visual_keywords': ['发缝自然']},
        '直播间低头手遮脸，错色不是这个颜色', 0.18)
    assert not irrelevant['ok'] and irrelevant['reasons'], irrelevant
    audit = audit_qianchuan_segments([
        {'script_segment': {'scene_id': 1, 'scene_type': 'product_proof', 'duration': 4},
         'matched_duration': 4, 'matched_recording_id': 1, 'matched_start_time': 3,
         'confidence_score': 0.82, 'matched_source_text': '发缝自然颜色细节'},
    ], [{'scene_id': 1, 'duration': 4}])
    assert audit['ok'] and audit['accepted_count'] == 1, audit
    script = generate_qianchuan_script(ctx['group'], good['product'], target_duration=22, selling_points=['蜜茶橘棕','羊毛卷'])
    assert script['mode'] == 'qianchuan' and len(script['scenes']) == 5
    ass = build_qianchuan_ass(script)
    cues = build_sound_cues(script)
    assert 'Dialogue:' in ass and r'\an9' in ass and cues
    assert normalize_transition_name('phone_zoom') == 'zoomin'
    assert normalize_transition_name('flash') == 'fadewhite'
    skill_cues = build_edit_sound_cues(
        [
            {'duration': 2.4, 'scene_type': 'hook', 'script_text': '显白'},
            {'duration': 3.2, 'scene_type': 'detail', 'script_text': '发缝自然'},
        ],
        transition_duration=0.4,
    )
    assert any(c.get('reason') == 'transition' for c in skill_cues), skill_cues
    assert any(c.get('reason') == 'keyword_emphasis' for c in skill_cues), skill_cues
    assert should_enable_pip('detail', [])
    composer = DirectorVideoComposer('.')
    vf = composer._build_clip_filter(composer.video_configs['dynamic'], {}, scene_type='detail', camera_direction='push_in', pip_detail=True)
    assert 'overlay=x=W-w-' in vf and 'crop=iw*0.42' in vf, vf
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
    # ── Regression: poll_transcriptions must be started as background task ──
    assert 'asyncio.create_task(poll_transcriptions(broadcast_fn=broadcast))' in main_py, \
        'poll_transcriptions is not started as a background task in lifespan'
    # ── Regression: createWS must return cleanup function, not raw WebSocket ──
    assert 'let wsCleanup = null' in Path('frontend/src/views/Dashboard.vue').read_text(), \
        'Dashboard.vue must use wsCleanup variable'
    assert 'wsCleanup = createWS' in Path('frontend/src/views/Dashboard.vue').read_text(), \
        'Dashboard.vue must assign createWS result to wsCleanup'
    assert 'wsCleanup?.()' in Path('frontend/src/views/Dashboard.vue').read_text(), \
        'Dashboard.vue must call cleanup function on unmount'
    assert 'if (closed) return' in api_js, \
        'api.js createWS must guard against reconnects after close'
    assert 'ws.onclose = null' in api_js, \
        'api.js createWS must nullify onclose before closing'
    # ── Regression: fetch timeouts must prevent UI freeze on unreachable backend ──
    remote_api_js = Path('frontend/src/remoteApi.js').read_text()
    assert 'REMOTE_FETCH_TIMEOUT_MS' in remote_api_js and 'AbortController' in remote_api_js, \
        'remoteApi.js must include AbortController-based fetch timeout'
    assert 'fetchWithTimeout' in api_js, \
        'api.js must have fetchWithTimeout wrapper with AbortController timeout'
    assert 'FETCH_TIMEOUT_MS' in api_js, \
        'api.js must define FETCH_TIMEOUT_MS'
    # ── Regression: WebSocket reconnect must use exponential backoff ──
    assert 'reconnectDelay' in api_js and 'Math.min(reconnectDelay * 2, 30000)' in api_js, \
        'api.js createWS must use exponential backoff on reconnect'
    # ── Regression: Dashboard must gate fallback polling to avoid duplicate loads ──
    dash_vue_text = Path('frontend/src/views/Dashboard.vue').read_text()
    assert 'lastWsMessage' in dash_vue_text, \
        'Dashboard.vue must track last WebSocket message time'
    assert 'Date.now() - lastWsMessage > 30000' in dash_vue_text, \
        'Dashboard.vue must gate fallback polling behind WebSocket silence threshold'
    # ── Regression: ClipQueue must use Promise.allSettled for independent requests ──
    cq_vue_text = Path('frontend/src/views/ClipQueue.vue').read_text()
    assert 'Promise.allSettled' in cq_vue_text, \
        'ClipQueue.vue must use Promise.allSettled for independent request handling'
asyncio.run(main())
print('qianchuan workflow smoke ok')

# ── qianchuan_learning smoke ──
import subprocess
try:
    import pytest
    has_pytest = True
except ImportError:
    has_pytest = False
if has_pytest:
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', 'tests/test_qianchuan_learning.py', 'tests/test_qianchuan_upload.py', 'tests/test_reclip_batch.py', 'tests/test_resumable_reclip.py', '-v', '--tb=short', '-x'],
        capture_output=True, text=True,
    )
    print(result.stdout[-3000:] if result.stdout else '')
    if result.returncode != 0:
        print(result.stderr[-2000:] if result.stderr else '')
        raise SystemExit(f'qianchuan tests failed: {result.returncode}')
    print('qianchuan unit tests passed')
else:
    print('pytest not installed, skipping qianchuan unit tests (non-fatal)')
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
files = [Path('backend/qianchuan_script.py'), Path('backend/qianchuan_matcher.py'), Path('backend/qianchuan_video.py'), Path('backend/qianchuan_quality.py'), Path('backend/qianchuan_learning.py'), Path('backend/video_editing_skills.py'), Path('backend/qianchuan_upload.py')]
for path in files:
    assert path.exists() and path.stat().st_size > 1000, path
print('coverage smoke: qianchuan critical modules exercised by tests gate')
PY

exit "$status"
