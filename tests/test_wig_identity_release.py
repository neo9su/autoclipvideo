import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release", ROOT / "scripts/wig_identity_release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)

SOURCE = '''async def load_group_context():
        if not group:
            return {}
        # LIVE_ONLY: preserve production-specific code
        return {
        "group": group_dict,
        }

def score_product_match(context, threshold=0.30):
    group = context.get("group") or {}
    best = {"score": 1.0}
    best["ok"] = best["score"] >= threshold
    return best
'''


def setup_release(tmp_path, crlf=False):
    backend = tmp_path / "backend"
    backend.mkdir()
    original = SOURCE.encode() if not crlf else b"\xef\xbb\xbf" + SOURCE.replace("\n", "\r\n").encode()
    (backend / "qianchuan_matcher.py").write_bytes(original)
    staged = tmp_path / "release-v1"
    release.prepare(backend, staged, ROOT / "backend/wig_identity.py")
    return backend, staged, original


@pytest.mark.parametrize("crlf", [False, True])
def test_stage_apply_rollback_restores_exact_original_bytes(tmp_path, crlf):
    backend, staged, original = setup_release(tmp_path, crlf)
    assert (backend / "qianchuan_matcher.py").read_bytes() == original
    assert not (backend / "wig_identity.py").exists()
    release.transition(staged)
    changed = (backend / "qianchuan_matcher.py").read_bytes()
    assert b"LIVE_ONLY" in changed and b"threshold=0.30" in changed
    assert b"load_identity_evidence" in changed
    release.transition(staged, rollback=True)
    assert (backend / "qianchuan_matcher.py").read_bytes() == original
    assert not (backend / "wig_identity.py").exists()


def test_apply_refuses_source_drift_before_any_change(tmp_path):
    backend, staged, original = setup_release(tmp_path)
    newer = original + b"\n# another developer's fix\n"
    (backend / "qianchuan_matcher.py").write_bytes(newer)
    with pytest.raises(ValueError, match="changed file"):
        release.transition(staged)
    assert (backend / "qianchuan_matcher.py").read_bytes() == newer
    assert not (backend / "wig_identity.py").exists()


def test_rollback_refuses_to_overwrite_newer_work(tmp_path):
    backend, staged, _ = setup_release(tmp_path)
    release.transition(staged)
    p = backend / "qianchuan_matcher.py"
    p.write_bytes(p.read_bytes() + b"\n# new fix\n")
    with pytest.raises(ValueError, match="changed file"):
        release.transition(staged, rollback=True)
    assert (backend / "wig_identity.py").exists()


def test_apply_refuses_corrupted_release_payload(tmp_path):
    backend, staged, original = setup_release(tmp_path)
    (staged / "after/wig_identity.py").write_text("# corrupt")
    with pytest.raises(ValueError, match="checksum"):
        release.transition(staged)
    assert (backend / "qianchuan_matcher.py").read_bytes() == original
    assert not (backend / "wig_identity.py").exists()


API_SOURCE = '''qianchuan_router = APIRouter(prefix="/api/v2/qianchuan", tags=["qianchuan"])
async def generate_qianchuan(request):
    context = await load_group_context(DB_PATH, request.group_id)
    match = score_product_match(context)
    return match

async def _run_qianchuan_pipeline(group_id):
    try:
        context = await load_group_context(DB_PATH, group_id)
        group = context["group"]
        script = generate_qianchuan_script(group)
    except Exception:
        raise

async def _qianchuan_generate_bg(group_id, script):
    async with _COMPOSE_SEM:
        try:
            voice_result = await voice_director.generate_voiceover(script=script)
        except Exception:
            raise
'''


def test_review_release_includes_api_health_and_exact_rollback(tmp_path):
    backend = tmp_path/'backend'; backend.mkdir()
    originals = {'qianchuan_matcher.py': SOURCE.encode(), 'api_v2.py': API_SOURCE.encode(),
                 'main.py': b'statuses = [(-4, "probe_fail")]\n'}
    for name, data in originals.items(): (backend/name).write_bytes(data)
    stage = tmp_path/'review-release'
    release.prepare(backend, stage, ROOT/'backend/wig_identity.py', ROOT/'backend')
    release.transition(stage)
    assert 'hold_for_review' in (backend/'api_v2.py').read_text()
    assert 'review_required' in (backend/'main.py').read_text()
    assert (backend/'wig_identity_routes.py').exists()
    release.transition(stage, rollback=True)
    assert sorted(p.name for p in backend.iterdir()) == sorted(originals)
    for name, data in originals.items(): assert (backend/name).read_bytes() == data


def test_review_patcher_covers_v2_run_and_tts_before_work():
    import ast
    v2 = API_SOURCE.replace('_run_qianchuan_pipeline', '_run_qianchuan_v2').replace('_qianchuan_generate_bg', '_qianchuan_v2_bg')
    v2 = v2[v2.index('async def _run_qianchuan_v2'):]
    patched = release.patch_review_api((API_SOURCE+'\n'+v2).encode()).decode()
    tree = ast.parse(patched)
    for n in tree.body:
        if isinstance(n, ast.AsyncFunctionDef):
            text = ast.get_source_segment(patched, n)
            assert 'hold_for_review' in text
            if 'voice_result =' in text:
                assert text.index('hold_for_review') < text.index('voice_result =')
            if 'script = generate' in text:
                assert text.index('hold_for_review') < text.index('script = generate')
