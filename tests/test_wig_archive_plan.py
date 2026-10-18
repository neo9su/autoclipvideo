import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from wig_archive_plan import build_archive_plan

PRODUCT={'id':1,'product_name':'小圆-夺回&人生【仿递针】混进口丝发型师精修日常大波浪假发套'}
BASE={'wig':'人生','color':'黑茶色','features':['长发','卷发'],'start_sec':5,'end_sec':15,
      'current_evidence':'这是人生','identity_confirmed':True,'visual_verified':True,'visual_style_signature':'dark-long-curly'}


def test_verified_name_and_stable_source_time():
    p=build_archive_plan(8,'source.mp4',[BASE],[PRODUCT])
    assert p['ready_count']==1
    assert p['segments'][0]['start_sec']==5
    assert '夺回&人生' in p['segments'][0]['relative_output']
    assert p['segments'][0]['segment_id']==build_archive_plan(8,'source.mp4',[BASE],[PRODUCT])['segments'][0]['segment_id']


def test_mentions_and_unverified_frames_cannot_become_named_archive():
    for update in [{'current_evidence':'夺回人生过了吗'}, {'visual_verified':False}]:
        assert build_archive_plan(8,'source.mp4',[dict(BASE,**update)],[PRODUCT])['ready_count']==0


def test_same_name_multiple_links_remain_options_and_overlap_is_flagged():
    p=build_archive_plan(8,'source.mp4',[BASE],[PRODUCT,dict(PRODUCT,id=2)])
    assert len(p['segments'][0]['catalogue_candidates'])==2
    p=build_archive_plan(8,'source.mp4',[BASE,dict(BASE,start_sec=10,end_sec=20)],[PRODUCT])
    assert p['ready_count']==0
    assert all(s['status']=='overlap_review' for s in p['segments'])
