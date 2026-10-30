import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from wig_name_recall import collect, prompt_evidence


def srt(*texts, gap=0):
    return '\n\n'.join(f'{i+1}\n00:00:{i*(2+gap):02},000 --> 00:00:{i*(2+gap)+2:02},000\n{t}' for i,t in enumerate(texts))


def products():
    return [{'id':i,'room_id':room,'product_name':'小圆-琥珀精灵【仿递针】长卷发'} for i,room in [(1,1),(2,1),(3,2)]]


def test_split_name_and_room_and_multilinks():
    r=collect(srt('这款叫琥珀','精灵真好看'), products(),1)
    assert len(r['candidates'])==1
    h=r['candidates'][0]
    assert h['product_ids']==[1,2] and h['current_assertion']
    assert h['start_sec']==0 and h['end_sec']==4
    assert not r['automatic_cart_eligible'] and not h['sku_verified']


def test_no_join_across_pause_or_future_confirmation():
    assert not collect(srt('这款叫琥珀','精灵',gap=3),products(),1)['candidates']
    h=collect(srt('下一款琥珀精灵'),products(),1)['candidates'][0]
    assert not h['current_assertion']


def test_full_source_not_only_prefix():
    raw=srt('废话'*5000,'这款叫琥珀精灵')
    r=collect(raw,products(),1)
    assert r['candidates'][0]['start_sec']==2
    assert '琥珀精灵' in prompt_evidence(r)


def test_generic_rejected_and_no_identity_assertion():
    p=[{'id':1,'room_id':1,'product_name':'小圆-爆款【仿递针】长卷发'}]
    assert not collect(srt('这是爆款'),p,1)['candidates']


def test_prompt_hints_cannot_feed_legacy_keyword_hits():
    import importlib.util
    path=Path(__file__).parents[1]/'scripts/stage_name_recall.py'
    spec=importlib.util.spec_from_file_location('stage_name',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    source='async def analyze_recording():\n    result = await _call_bedrock(text)\n    prod_names = match_products(text, await load_short_names())\n'
    patched=module.patch(source)
    assert 'product_match_text = text' in patched
    assert 'match_products(product_match_text, await load_short_names())' in patched
    assert 'match_products(text,' not in patched
