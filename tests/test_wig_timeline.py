import importlib.util
from pathlib import Path
import sqlite3
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
from wig_timeline import analyze_timeline, parse_srt, milliseconds

CATALOG = [{'key': 'a', 'aliases': ['元气森林']}, {'key': 'b', 'aliases': ['妲己狐']}]


def srt(*texts):
    return '\n\n'.join(f'{i+1}\n00:00:{i*2:02d},000 --> 00:00:{i*2+1:02d},500\n{text}' for i,text in enumerate(texts))


def test_product_change_does_not_leak_identity_into_neighboring_cues():
    r = analyze_timeline(srt('现在戴的是元气森林', '发丝很自然', '接下来换一款妲己狐', '这顶就是妲己狐'), CATALOG)
    assert [c['state'] for c in r['segments']] == ['single_product_text_evidence','unassigned','possible_product_switch','single_product_text_evidence']
    assert r['segments'][1]['product_keys'] == []
    assert all(not c['eligible_for_render'] for c in r['segments'])
    assert not r['visual_verified'] and not r['sku_verified']


def test_same_cue_multiple_products_requires_review_even_for_negated_comparison():
    r = analyze_timeline(srt('这不是元气森林，是妲己狐'), CATALOG)
    assert r['segments'][0]['state'] == 'multiple_product_mentions'
    assert r['segments'][0]['approval'] == 'review_required'


def test_alias_collision_is_not_resolved_by_guessing():
    catalog = [{'key': 'a', 'aliases': ['元气森林']}, {'key': 'c', 'aliases': ['元气森林']}]
    r = analyze_timeline(srt('元气森林看这里'), catalog)
    assert r['segments'][0]['state'] == 'ambiguous_alias'


@pytest.mark.parametrize('alias', ['卷发','长直发','假发','自然黑','免发网','a'])
def test_generic_hair_traits_cannot_certify_a_product(alias):
    r = analyze_timeline(srt(alias), [{'key': 'a', 'aliases': [alias]}])
    assert r['segments'][0]['state'] == 'unassigned'
    assert r['rejected_aliases']


def test_other_product_cannot_become_target_evidence():
    r = analyze_timeline(srt('妲己狐'), CATALOG, target_key='a')
    assert r['segments'][0]['state'] == 'other_product_mentioned'
    assert r['segments'][0]['foreign_product_keys'] == ['b']


def test_invalid_target_is_not_silently_accepted():
    with pytest.raises(ValueError): analyze_timeline(srt('元气森林'), CATALOG, target_key='missing')


def test_exact_original_times_bom_crlf_multiline_and_dot_milliseconds():
    cues, errors = parse_srt('\ufeff1\r\n00:01:01.123-->00:01:04.456\r\n元气\r\n森林\r\n')
    assert not errors and cues[0]['text'] == '元气 森林'
    assert (cues[0]['start_ms'], cues[0]['end_ms']) == (61123,64456)
    r = analyze_timeline('\ufeff1\n00:00:01,123 --> 00:00:04,456\n元气 森林', CATALOG)
    assert r['segments'][0]['matched_aliases'] == ['元气森林']


@pytest.mark.parametrize('timestamp', ['00:60:00,000','00:00:60,000','bad','-1:00:00,000'])
def test_malformed_timestamps_rejected(timestamp):
    with pytest.raises(ValueError): milliseconds(timestamp)


def test_overlap_and_bad_blocks_are_reported_without_approving_content():
    src='1\n00:00:00,000 --> 00:00:03,000\n元气森林\n\n2\n00:00:02,000 --> 00:00:04,000\n妲己狐\n\n3\nbad\nunknown'
    r = analyze_timeline(src, CATALOG)
    assert len(r['parse_errors']) == 2
    assert all(c['state']=='ambiguous_timing' for c in r['segments'])
    assert not r['eligible_for_render']


def test_full_transcript_is_checked_including_late_product_change():
    src=srt('元气森林') + '\n\n2\n00:20:00,000 --> 00:20:03,000\n妲己狐'
    r=analyze_timeline(src,CATALOG)
    assert r['cue_count']==2 and r['segments'][-1]['product_keys']==['b']


def test_catalog_and_source_hashes_make_results_reproducible():
    a=analyze_timeline(srt('元气森林'),CATALOG)
    b=analyze_timeline(srt('元气森林'),CATALOG)
    assert a==b
    assert a['source_sha256']!=analyze_timeline(srt('妲己狐'),CATALOG)['source_sha256']


@pytest.mark.parametrize('text', ['别摘掉牌，不然不能退','换个角度看一下','我们下一个客户'])
def test_packaging_angle_and_customer_turns_are_not_product_switches(text):
    assert analyze_timeline(srt(text),CATALOG)['segments'][0]['state']=='unassigned'


def test_spoken_link_and_color_numbers_are_evidence_not_sku_assignments():
    r=analyze_timeline(srt('看八号链接，五号颜色，另一个是12号款'),CATALOG)
    refs=r['segments'][0]['spoken_references']
    assert [ref['type'] for ref in refs]==['link','color','style']
    assert all(ref['resolved_product_key'] is None for ref in refs)
    assert r['unresolved_spoken_reference_count']==3
    assert r['segments'][0]['product_keys']==[]


def test_spoken_link_changes_are_review_points_not_identity_assignments():
    r=analyze_timeline(srt('八号链接','8号链接','五号色','十二号链接'),CATALOG)
    changes=r['link_reference_changes']
    assert len(changes)==1
    assert changes[0]['previous_link_number']==8 and changes[0]['link_number']==12
    assert changes[0]['product_key'] is None and changes[0]['requires_visual_review']


def test_multiple_links_in_one_cue_do_not_create_a_false_single_link_state():
    r=analyze_timeline(srt('八号链接','8号链接和十二号链接','十二号链接'),CATALOG)
    assert r['link_reference_changes']==[]


def test_future_sales_discussion_is_not_reported_as_current_switch():
    r=analyze_timeline(srt('我们这款是卖完下一款'),CATALOG)
    assert r['segments'][0]['state']=='future_switch_discussion'


def test_mixed_traditional_asr_matches_without_changing_original_evidence():
    r=analyze_timeline(srt('這款是元氣森林，八號鏈接','這款賣完下一款'),CATALOG)
    assert r['segments'][0]['product_keys']==['a']
    assert r['segments'][0]['spoken_references'][0]['number']==8
    assert r['segments'][1]['state']=='future_switch_discussion'
    assert '元氣森林' in r['segments'][0]['text']


def test_cli_audit_uses_explicit_ids_room_catalog_and_preserves_database(tmp_path):
    spec=importlib.util.spec_from_file_location('timeline_cli',ROOT/'scripts/audit_wig_timeline.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    dbpath=tmp_path/'live.db'
    with sqlite3.connect(dbpath) as db:
        db.execute('CREATE TABLE products(id,short_name,room_id,enabled)')
        db.executemany('INSERT INTO products VALUES(?,?,?,1)',[(1,'元气森林',2),(2,'元气森林',3)])
        db.execute('CREATE TABLE recordings(id,filename,room_id)')
        db.execute("INSERT INTO recordings VALUES(7,'2_test.mp4',2)")
    (tmp_path/'2').mkdir();(tmp_path/'2/2_test.srt').write_text(srt('元气森林'),encoding='utf8')
    before=dbpath.read_bytes()
    report=module.audit_recordings(dbpath,[7],[tmp_path])['reports'][0]
    assert report['segments'][0]['product_keys']==['catalog:1']
    assert dbpath.read_bytes()==before
    with pytest.raises(ValueError):module.audit_recordings(dbpath,list(range(21)),[tmp_path])
