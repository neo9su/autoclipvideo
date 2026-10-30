import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / 'backend'))
from qianchuan_product_evidence import product_evidence, load_transcripts

PRODUCT = dict(id=1, enabled=1, product_name='小圆-夺回&人生【仿递针】日常大波浪假发套')


def test_group_self_hits_never_promote_unrelated_product():
    context = {'group': {'wig_model': '自然黑真发质感全头套', 'wig_color': '自然黑'},
               'products': [{'id': 72, 'product_name': '假发女漫画刘海头顶补发片', 'keywords': '自然黑'}]}
    result = product_evidence(context, product_id='72')
    assert not result['ok'] and result['score'] == 0 and result['product'] is None


def test_alias_group_evidence_works_with_long_catalogue_name():
    result = product_evidence({'group': {'wig_model': '人生'}, 'products': [PRODUCT]})
    assert result['ok'] and result['product']['id'] == 1 and result['hits'] == ['人生']


def test_current_spoken_name_supported_but_future_and_comparison_not():
    for text in ['这是夺回，看看发缝', '现在戴的是人生']:
        assert product_evidence({'group': {}, 'products': [PRODUCT], 'srt_text': text})['ok']
    for text in ['有没有人生', '待会介绍夺回', '和人生相比更好看']:
        assert not product_evidence({'group': {}, 'products': [PRODUCT], 'srt_text': text})['ok']


def test_other_style_mentioned_in_long_srt_cannot_override_group_style():
    other = dict(id=2, enabled=1, product_name='小圆-射手座【仿递针】长卷发假发')
    result = product_evidence({'group': {'wig_model': '人生'}, 'products': [other, PRODUCT],
                               'srt_text': '这是射手座'})
    assert result['product']['id'] == 1


def test_subtitle_contract_reads_late_name_and_reports_missing(tmp_path):
    p = tmp_path / 'room.mp4.srt'
    p.write_text('\ufeff' + '普通讲解' * 3000 + '这是夺回', encoding='utf-8')
    text, audit = load_transcripts(['room.mp4', 'missing.mp4'], lambda n: p if n == 'room.mp4' else None)
    assert '这是夺回' in text and not text.startswith('\ufeff')
    assert audit[0]['characters'] > 8000
    assert audit[1]['error'] == 'subtitle_not_resolved'
