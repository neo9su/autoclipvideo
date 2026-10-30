import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from audit_wig_visibility import tilted_border_pairs,foreground_risk,apply_visibility_hold


def test_separated_tilted_borders_cover_anchor():
    assert tilted_border_pairs([[20,50,80,350],[300,50,360,350]],400,400)


def test_axis_aligned_door_edges_are_not_this_specific_proposal():
    assert not tilted_border_pairs([[20,50,20,350],[300,50,300,350]],400,400)


def test_short_edges_cannot_create_large_foreground_proposal():
    assert not tilted_border_pairs([[20,50,30,100],[300,50,310,100]],400,400)


def test_parallel_edges_on_one_side_do_not_cover_target_prior():
    assert not tilted_border_pairs([[10,50,70,350],[90,50,150,350]],400,400)


def test_crossing_nonparallel_edges_not_rectangle_evidence():
    assert not tilted_border_pairs([[20,50,80,350],[360,50,300,350]],400,400)


def test_image_path_detects_synthetic_tilted_rigid_foreground():
    import cv2
    import numpy as np
    image=np.zeros((400,400,3),dtype=np.uint8)
    cv2.polylines(image,[np.array([[20,50],[300,50],[360,350],[80,350]],dtype=np.int32)],True,(255,255,255),4)
    r=foreground_risk(image)
    assert r['risk_candidate'] and not r['screen_confirmed'] and not r['target_verified']


def test_foreground_risk_invalidates_cached_stable_candidate():
    original=dict(candidate='no_visible_style_change',reasons=[])
    held=apply_visibility_hold(original,[dict(timestamp_s=13)])
    assert held['candidate']=='uncertain'
    assert held['previous_candidate']=='no_visible_style_change'
    assert original==dict(candidate='no_visible_style_change',reasons=[])


def test_negative_geometry_does_not_certify_head_or_identity():
    r=apply_visibility_hold(dict(candidate='matching_style_rewear_candidate'),[])
    assert not r['target_verified'] and not r['head_state_verified']
    assert not r['sku_verified'] and not r['eligible_for_render']
    assert r['requires_visual_review']


def test_prior_approval_flags_cannot_survive_guard():
    r=apply_visibility_hold(dict(candidate='no_visible_style_change',eligible_for_render=True,sku_verified=True,physical_identity_verified=True,target_verified=True),[])
    assert not any(r[k] for k in ['eligible_for_render','sku_verified','physical_identity_verified','target_verified'])


def test_mismatched_cached_manifest_stops_before_output_or_decode(tmp_path):
    import hashlib
    import subprocess
    clip=tmp_path/'source.mp4';clip.write_bytes(b'unchanged test source')
    manifest=tmp_path/'manifest.json'
    manifest.write_text(json.dumps({'samples':[dict(id='one',video='source.mp4',source_start_s=0,duration_s=10,sha256=hashlib.sha256(clip.read_bytes()).hexdigest(),expected='uncertain')]}))
    cached=tmp_path/'cached.json';cached.write_text(json.dumps(dict(manifest_sha256='wrong',results=[])))
    out=tmp_path/'new.json'
    script=Path(__file__).resolve().parents[1]/'scripts'/'audit_wig_visibility.py'
    result=subprocess.run([sys.executable,str(script),'--manifest',str(manifest),'--feature-report',str(cached),'--output',str(out)],capture_output=True,text=True,timeout=10)
    assert result.returncode != 0 and 'different manifest' in result.stderr
    assert not out.exists() and clip.read_bytes()==b'unchanged test source'
