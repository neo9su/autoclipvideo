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
