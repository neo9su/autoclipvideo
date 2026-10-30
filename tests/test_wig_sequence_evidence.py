import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import pytest
from backend.wig_sequence_evidence import analyze_sequence


def frame(t, state, **extra):
    return dict(time_sec=t, state=state, head_visible=True, reason='可见证据', **extra)


def test_finished_removal_and_uncertain_wearing_are_conflicts_not_invented_labels():
    frames = [frame(988, 'taking_off'), frame(990, 'wearing')]
    frames[0]['reason'] = '符合取下假发后的状态'
    frames[1]['reason'] = '头发覆盖头部，无法确认是否佩戴假发'
    result = analyze_sequence(frames)
    assert [r['head_state'] for r in result['observations']] == ['uncertain', 'uncertain']
    assert result['issue_count'] == 2 and result['wearing_candidate_runs'] == []
    assert result['observations'][0]['raw'] == frames[0]


def test_bare_head_and_hairnet_colors_never_become_product_features():
    result = analyze_sequence([frame(1, 'no_wig', color='black'), frame(2, 'hair_net', color='black'),
                               frame(3, 'holding_only', color='brown')])
    assert all(r['product_features'] == {} for r in result['observations'])
    assert result['observations'][2]['held_wig_reported']
    assert result['observations'][2]['head_state'] == 'uncertain'


def test_same_appearance_after_takeoff_or_gap_does_not_merge_or_certify_rewear():
    frames = [frame(1, 'wearing', color='brown'), frame(2, 'wearing', color='brown'),
              frame(3, 'taking_off'), frame(4, 'no_wig'), frame(5, 'putting_on'),
              frame(6, 'wearing', color='brown'), frame(20, 'wearing', color='brown')]
    result = analyze_sequence(frames)
    assert [r['sample_count'] for r in result['wearing_candidate_runs']] == [2, 1, 1]
    assert len(result['identity_gaps']) == 1
    assert result['same_object_rewear'] == 'unverified' and not result['eligible_for_render']


def test_invalid_times_duplicates_and_missing_visibility_cannot_supply_runs():
    for t in (float('nan'), float('inf'), -1, None):
        with pytest.raises(ValueError): analyze_sequence([frame(t, 'wearing')])
    with pytest.raises(ValueError): analyze_sequence([frame(1, 'wearing'), frame(1, 'no_wig')])
    f=frame(1,'wearing');f['head_visible']=False
    assert not analyze_sequence([f])['wearing_candidate_runs']


def test_spoken_aliases_preserve_different_urls_and_never_confirm_physical_rewear():
    from backend.wig_sequence_evidence import attach_catalogue_evidence
    products=[{'id':i, 'product_name':'小圆-夺回&人生【仿递针】长卷发',
               'product_url':f'https://example.invalid/{i}'} for i in (1,2)]
    frames=[frame(t,'wearing') for t in (1,2,3)] + [frame(4,'no_wig')] + [frame(t,'wearing') for t in (5,6,7)]
    sequence=analyze_sequence(frames)
    cues=[{'start_sec':1.1,'end_sec':2.1,'text':'这是夺回'},
          {'start_sec':5.1,'end_sec':6.1,'text':'这是人生'}]
    result=attach_catalogue_evidence(sequence,cues,products)
    assert 'catalogue_candidates' not in sequence['wearing_candidate_runs'][0]
    assert all(len(r['catalogue_candidates']) == 2 for r in result['wearing_candidate_runs'])
    assert result['run_comparisons'][0]['name_relation'] == 'same_spoken_name_candidates'
    assert result['run_comparisons'][0]['same_physical_object'] == 'unverified'
    assert not result['eligible_for_render']


def test_transition_names_history_and_future_do_not_name_current_wig():
    from backend.wig_sequence_evidence import attach_catalogue_evidence
    sequence=analyze_sequence([frame(1,'wearing'),frame(2,'wearing'),frame(3,'taking_off'),
                               frame(4,'no_wig'),frame(5,'wearing'),frame(6,'wearing')])
    products=[{'id':1,'product_name':'小圆-人生【仿递针】长卷发'}]
    cues=[{'start_sec':3,'end_sec':4,'text':'这是人生'},
          {'start_sec':5.1,'end_sec':5.8,'text':'人生已过'}]
    result=attach_catalogue_evidence(sequence,cues,products)
    assert all(r['catalogue_candidates'] == [] for r in result['wearing_candidate_runs'])


def test_two_current_names_remain_conflicting_candidates():
    from backend.wig_sequence_evidence import attach_catalogue_evidence
    sequence=analyze_sequence([frame(t,'wearing') for t in (1,2,3,4,5)])
    products=[{'id':1,'product_name':'小圆-人生【仿递针】长卷发'},
              {'id':2,'product_name':'小圆-天蝎座【仿递针】长卷发'}]
    cues=[{'start_sec':1,'end_sec':2,'text':'这是人生'},
          {'start_sec':4,'end_sec':5,'text':'这是天蝎座'}]
    result=attach_catalogue_evidence(sequence,cues,products)
    assert result['wearing_candidate_runs'][0]['name_evidence_status'] == 'multiple_current_names'
    assert len(result['wearing_candidate_runs'][0]['catalogue_candidates']) == 2
