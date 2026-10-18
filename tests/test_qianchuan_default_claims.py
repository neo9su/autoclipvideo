import importlib.util
from pathlib import Path
import sys
import pytest

ROOT=Path(__file__).parents[1]
sys.path.insert(0,str(ROOT/'backend'))
spec=importlib.util.spec_from_file_location('claims_script',ROOT/'backend/qianchuan_script.py')
module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)


def test_default_copy_has_no_automatic_benefits_or_cart_promises():
    script=module.generate_qianchuan_script({'wig_model':'人生','wig_color':'棕色'})
    speech=''.join(s['voiceover_text'] for s in script['scenes'])
    for term in ['显白','免发网','不用戴发网','稳固','也稳','显脸小','30 秒','小黄车','下单']:
        assert term not in speech
    assert script['selling_points']==[] and script['selling_points_source']=='none'
    assert script['version']=='1.1'
    assert len(script['scenes'])==5
    assert script['scenes'][0]['scene_type']=='result_hook'
    assert script['scenes'][-1]['timestamp_end']==script['target_duration']
    assert script['retention_hooks']


def test_caller_keywords_are_not_automatically_spoken_or_added_to_every_subtitle():
    script=module.generate_qianchuan_script({},selling_points=['免发网','稳固','发丝','免发网'])
    assert script['selling_points']==['免发网','稳固','发丝']
    assert script['selling_points_source']=='caller_supplied_unverified'
    for scene in script['scenes']:
        assert '免发网' not in scene['voiceover_text'] and '稳固' not in scene['voiceover_text']
        assert all(kw in scene['voiceover_text'] for kw in scene['subtitle_keywords'])


def test_patch_removes_learned_product_claim_injection_and_preserves_timing():
    sys.path.insert(0,str(ROOT/'scripts'))
    from prepare_script_claims_deploy import patch_script
    source='''
KEY_SELLING_POINTS = ["免发网"]
def generate_qianchuan_script():
    points=[]
    merged_points=points + KEY_SELLING_POINTS
    scene_text = {"pain_point":"legacy assertion"}
    hooks = ["30 秒显白"]
    if learned_hook:
        hooks.insert(0,learned_hook)
    if learned_phrases:
        scene_text["cta"]=learned_phrases[0]
    num_loops = math.ceil(duration / LOOP_DURATION)
    subtitles = matched_keywords or merged_points[:3]
    return {"version": "1.0", "selling_points": merged_points,}
'''
    patched=patch_script(source)
    assert 'hooks.insert' not in patched and 'learned_phrases[0]' not in patched
    assert 'math.ceil(duration / LOOP_DURATION)' in patched
    assert 'legacy assertion' not in patched
    with pytest.raises(RuntimeError,match='drift'):
        patch_script(patched)
