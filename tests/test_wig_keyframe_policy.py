import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from audit_wig_keyframes import compare_appearance,parse_frames


def frame(index,**changes):
    d=dict(index=index,head='hair_visible',color='warm_brown',bangs='full',texture='straight')
    d.update(changes);return d


def test_black_unworn_middle_is_not_a_black_product():
    result=compare_appearance([frame(0),frame(1,head='close_fitting_or_net',color='black',bangs='uncertain',texture='uncertain'),frame(2)])
    assert result['candidate']=='matching_style_rewear_candidate'
    assert result['differences']==[]
    assert not result['eligible_for_render'] and not result['sku_verified']
    assert not result['physical_identity_verified']


def test_same_color_different_texture_is_still_a_review_conflict():
    result=compare_appearance([frame(0),frame(1,head='close_fitting_or_net'),frame(2,texture='curly')])
    assert result['candidate']=='different_visible_style'
    assert result['differences']==['texture']


def test_same_texture_different_bangs_is_not_same_style():
    result=compare_appearance([frame(0),frame(1),frame(2,bangs='curtain')])
    assert result['candidate']=='different_visible_style'


def test_unknown_color_cannot_be_filled_from_previous_frame():
    result=compare_appearance([frame(0),frame(1),frame(2,color='uncertain')])
    assert result['candidate']=='uncertain'


def test_occluded_presenter_cannot_be_replaced_by_phone_image():
    result=compare_appearance([frame(0),frame(1),frame(2,head='occluded')])
    assert result['candidate']=='uncertain'


def test_appearance_matching_without_unworn_state_is_not_rewear():
    result=compare_appearance([frame(0),frame(1),frame(2)])
    assert result['candidate']=='no_visible_style_change'
    assert result['requires_visual_review']


def test_unknown_middle_does_not_certify_cycle():
    result=compare_appearance([frame(0),frame(1,head='uncertain'),frame(2)])
    assert result['candidate']=='uncertain'


def test_observations_must_keep_frame_order():
    data=json.dumps(dict(frames=[frame(1),frame(0),frame(2)]))
    frames,error=parse_frames(data)
    assert error and frames is None


def test_invalid_feature_never_becomes_a_guess():
    frames,error=parse_frames(json.dumps(dict(frames=[frame(0),frame(1),frame(2,texture='probably straight')])) )
    assert error and compare_appearance(frames)['candidate']=='uncertain'
