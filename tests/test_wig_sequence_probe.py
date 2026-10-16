import hashlib
import importlib.util
import json
from pathlib import Path
import sys

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import audit_wig_sequence as probe
import pytest


def observation(**overrides):
    d = dict(relation='visually_matching_rewear', before='brown straight', after='brown straight', events=[dict(start_s=1,end_s=2,action='remove',evidence='lifted wig')], identity_gap=False, reason='visible sequence')
    d.update(overrides)
    return json.dumps(d)


def test_invalid_or_truncated_json_is_unknown():
    d, error = probe.parse_observation('{"relation":"visually_matching_rewear"', 20)
    assert error and d['relation'] == 'uncertain'


def test_event_times_cannot_escape_clip():
    d, error = probe.parse_observation(observation(events=[dict(start_s=19,end_s=25,action='put_on',evidence='wig lowered')]),20)
    assert error and d['relation'] == 'uncertain'


def test_absent_uncertainty_not_silently_assumed_false():
    d=json.loads(observation());del d['identity_gap']
    parsed,error=probe.parse_observation(json.dumps(d),20)
    assert error and parsed['relation']=='uncertain'


def test_valid_prediction_preserves_uncertainty():
    d,error=probe.parse_observation(observation(relation='uncertain',identity_gap=True),20)
    assert not error and d['identity_gap'] is True


def test_manifest_checks_source_hash_before_model_load(tmp_path):
    clip=tmp_path/'clip.mp4';clip.write_bytes(b'untouched source')
    manifest=tmp_path/'manifest.json'
    manifest.write_text(json.dumps({'samples':[dict(id='one', video='clip.mp4',duration_s=10,source_start_s=1,sha256='incorrect',expected='uncertain')]}))
    with pytest.raises(ValueError,match='checksum'):probe.read_cases(manifest)
    assert clip.read_bytes()==b'untouched source'


def test_valid_manifest_retains_label_for_offline_evaluation(tmp_path):
    clip=tmp_path/'clip.mp4';clip.write_bytes(b'untouched source')
    manifest=tmp_path/'manifest.json'
    manifest.write_text(json.dumps({'samples':[dict(id='one',video='clip.mp4',duration_s=10,source_start_s=1,sha256=hashlib.sha256(clip.read_bytes()).hexdigest(),expected='different_style_or_color')]}))
    cases=probe.read_cases(manifest)
    assert cases[0]['expected']=='different_style_or_color'
    assert cases[0]['_path'] == str(clip.resolve())


def test_same_style_requires_complete_cycle():
    d,error=probe.parse_observation(observation(),20)
    assert error and d['relation']=='uncertain'


def test_matching_appearance_does_not_erase_identity_gap():
    events=[dict(start_s=i,end_s=i+1,action=action,evidence='visible action') for i,action in enumerate(['remove','unworn','put_on'])]
    d,error=probe.parse_observation(observation(events=events,identity_gap=True),20)
    assert not error and d['identity_gap'] is True


def test_complete_observed_cycle_is_still_only_model_observation():
    events=[dict(start_s=i,end_s=i+1,action=action,evidence='visible action') for i,action in enumerate(['remove','unworn','put_on'])]
    d,error=probe.parse_observation(observation(events=events),20)
    assert not error and d['relation']=='visually_matching_rewear'
