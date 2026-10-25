from pathlib import Path
import importlib.util
import pytest

path = Path(__file__).parents[1] / 'scripts/patch_qianchuan_product_evidence.py'
spec = importlib.util.spec_from_file_location('evidence_patch', path)
patcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)

SOURCE = '''
async def load_group_context():
    production_only = True
    query = """ORDER BY {room_order} id DESC
                   LIMIT 30"""
    recordings_dir = "legacy"
    srt_texts = []
    srt_texts.append(f.read()[:8000])
    group_dict = dict(group)
    return {"srt_text": "\\n".join(srt_texts),}

def score_product_match(context, threshold=0.30):
    group = context.get("group") or {}
    corpus = " ".join(["legacy"])
    candidate_tokens = []
    exact_bonus = 0.10
    return {}
'''


def test_scoped_patch_preserves_production_only_code_and_default():
    result = patcher.patch_source(SOURCE)
    assert 'production_only = True' in result
    assert 'threshold=0.30' in result
    assert 'LIMIT 30' not in result
    assert 'load_transcripts' in result and 'subtitle_audit' in result
    assert 'candidate_tokens' not in result
    assert 'exact_bonus' not in result


def test_repeat_patch_refuses_instead_of_overwriting():
    with pytest.raises(AssertionError):
        patcher.patch_source(patcher.patch_source(SOURCE))
