import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from wig_visual_consensus import reconcile


def run(job,state='stable_wearing',signature='棕|长|直|齐刘海|中分'):
    return {'job_id':job,'input_artifact_id':'same-source','observations':[{'time_sec':10,'wear_state':state,'style_signature':signature,'confidence':0.99}]}


def test_confidence_does_not_override_conflict():
    result=reconcile([run(1),run(2,'no_wig')])
    assert result['conflicting_timestamps']==1
    assert not result['automatic_merge_approved']


def test_agreement_not_identity_proof():
    r=reconcile([run(1),run(2)])
    assert r['conflicting_timestamps']==0
    assert not r['eligible_for_render']
    assert r['points'][0]['status']=='review_required'


def test_reject_wrong_source_duplicate_job_and_bad_time():
    other=run(2);other['input_artifact_id']='other'
    with pytest.raises(ValueError):reconcile([run(1),other])
    with pytest.raises(ValueError):reconcile([run(1),run(1)])
    bad=run(1);bad['observations'][0]['time_sec']=float('nan')
    with pytest.raises(ValueError):reconcile([bad])


def test_unknown_padding_is_not_appearance_conflict():
    r=reconcile([run(1,'transition','未知'),run(2,'transition','未知|未知|未知|未知|未知')])
    assert r['conflicting_timestamps']==0
    assert 'incomplete_visual_features' in r['points'][0]['issues']
