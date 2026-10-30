import hashlib,importlib.util
from pathlib import Path
import pytest
p=Path(__file__).parents[1]/'scripts/restore_aid_transcript_result.py'
s=importlib.util.spec_from_file_location('restore',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

def state(tmp_path,text,duration=266):
    path=tmp_path/'evidence.srt';raw=text.encode('utf-8-sig');path.write_bytes(raw)
    return dict(source_video={'format':{'duration':str(duration)}},transcript=str(path),transcript_sha256=hashlib.sha256(raw).hexdigest())

def test_bom_subtitles_with_verified_hash_and_bounds(tmp_path):
    item=state(tmp_path,'1\n00:00:01,000 --> 00:00:03,500\n口播\n')
    assert m.validated_subtitle(item)[0]==266
    item['transcript_sha256']='changed'
    with pytest.raises(AssertionError):m.validated_subtitle(item)

@pytest.mark.parametrize('duration,text',[(21,'1\n00:00:01,000 --> 00:00:03,000\n口播'),(266,''),(266,'1\n00:05:00,000 --> 00:05:01,000\n口播')])
def test_short_empty_or_out_of_bounds_results_are_not_imported(tmp_path,duration,text):
    with pytest.raises(AssertionError):m.validated_subtitle(state(tmp_path,text,duration))
