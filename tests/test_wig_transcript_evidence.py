import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'backend'))
from wig_transcript_evidence import parse_srt, corroborate_quote, catalogue_mentions


def test_milliseconds_multiline_and_malformed_cues():
    cues=parse_srt('\ufeff1\r\n00:00:06,125 --> 00:00:07.250\r\n这是\r\n人生\r\n\r\n2\r\n00:99:00,000 --> 00:99:01,000\r\nbad')
    assert cues==[{'start_sec':6.125,'end_sec':7.25,'text':'这是人生'}]
    assert corroborate_quote(cues,'这是，人生','夺回&人生',5,10)['verified']


def test_historical_context_cannot_be_removed_from_quote():
    cues=parse_srt('1\n00:00:05,000 --> 00:00:06,000\n这是人生\n\n2\n00:00:06,100 --> 00:00:07,000\n过了吗')
    assert not corroborate_quote(cues,'这是人生','夺回&人生',0,10)['verified']


def test_quote_does_not_bridge_long_pause_or_window():
    cues=parse_srt('1\n00:00:05,000 --> 00:00:06,000\n这是\n\n2\n00:00:16,000 --> 00:00:17,000\n人生')
    assert not corroborate_quote(cues,'这是人生','夺回&人生',0,20)['verified']
    assert not corroborate_quote(cues,'这是','夺回&人生',7,20)['verified']


def test_same_name_links_and_history_mentions_stay_separate():
    cues=parse_srt('1\n00:00:05,000 --> 00:00:06,000\n这是人生\n\n2\n00:00:16,000 --> 00:00:17,000\n夺回已过')
    products=[{'id':i,'product_name':'小圆-夺回&人生【仿递针】长卷发'} for i in (1,2)]
    hits=catalogue_mentions(cues,products)
    assert len(hits)==2 and hits[0]['catalogue_ids']==[1,2]
    assert hits[0]['current_assertion'] and not hits[1]['current_assertion']
    assert not any(h['visual_verified'] for h in hits)
