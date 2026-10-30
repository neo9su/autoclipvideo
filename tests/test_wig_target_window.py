import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from wig_target_window import choose


def b(name='琥珀精灵',start=0,end=60):return dict(wig=name,color='浅棕',start_sec=start,end_sec=end,current_evidence='这款叫'+name,complete=True)
def cues():return [{'start_sec':1,'end_sec':3,'text':'这款叫琥珀精灵'},{'start_sec':100,'end_sec':102,'text':'这款叫天蝎座'},{'start_sec':398,'end_sec':400,'text':'结束'}]
def target():return {'wig_model':'琥珀精灵','wig_color':'浅棕色'}


def test_target_beats_longest_other_product():
    first=b();assert choose([first,b('天蝎座',90,390)],target(),cues()) is first


def test_no_fallback_on_missing_quote_wrong_color_short_or_conflict():
    cases=[[b('天蝎座')],[{**b(),'current_evidence':'主播没说过的话'}],[{**b(),'color':'黑色'}],[b(end=20)],[b(),b('天蝎座',20,100)]]
    for windows in cases:
        with pytest.raises(ValueError):choose(windows,target(),cues())


def test_generic_or_multiple_targets_require_review():
    for name in ['长卷发','','人生/天蝎座']:
        with pytest.raises(ValueError):choose([b()],{'wig_model':name},cues())


def test_future_mention_cannot_confirm_current():
    cs=[{'start_sec':1,'end_sec':3,'text':'下一款这款叫琥珀精灵'},cues()[-1]]
    with pytest.raises(ValueError):choose([b()],target(),cs)
