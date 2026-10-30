import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from patch_group_identity_guards import reusable_product_names,patch_editor


def test_conflicting_or_unknown_names_do_not_reuse():
    for old,new in [('人生',['琥珀精灵']),('',[]),('卷发',['卷发']),('人生,天蝎座',['人生','天蝎座']),('人生',[])]:
        assert not reusable_product_names(old,new)
    assert reusable_product_names('琥珀精灵',['琥珀精灵'])


def test_fallback_stops_at_gap_and_duration():
    from types import SimpleNamespace as S
    source='def _select_realistic_window(candidates):\n    target_max=45\n    if True:\n        chosen = candidates[:REALISTIC_MAX_SEGMENTS]\n    return chosen\n'
    ns={'REALISTIC_MAX_SEGMENTS':8};exec(patch_editor(source),ns)
    a=S(start=0,end=20,duration=20);b=S(start=100,end=120,duration=20)
    assert ns['_select_realistic_window']([a,b])==[a]
    c=S(start=20,end=40,duration=20);d=S(start=40,end=60,duration=20)
    assert ns['_select_realistic_window']([a,c,d])==[a,c]
