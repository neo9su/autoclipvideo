import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from wig_text_review import review_subtitles

RAW=b'1\n00:00:01,000 --> 00:00:02,000\nhello\n\n2\n00:10:00,000 --> 00:10:01,000\noutside'


def test_scope_and_same_name_urls_are_preserved_without_mutations(tmp_path,monkeypatch):
    (tmp_path/'worker.py').write_text('# isolated')
    products=[{'id':i,'product_name':'same','product_url':f'https://example.invalid/{i}'} for i in (1,2)]
    def run(args,**kwargs):
        payload=json.loads(kwargs['input'])
        assert len(payload['cues']) == 1 and payload['cues'][0]['text']=='hello'
        assert args[1]=='-I' and kwargs['timeout']==30
        return SimpleNamespace(stdout=json.dumps({'candidates':[{'catalogue_ids':[1,2]}]}).encode())
    monkeypatch.setattr(subprocess,'run',run)
    result=review_subtitles(RAW,products,0,600,runtime=tmp_path)
    assert [p['product_url'] for p in result['candidates'][0]['product_candidates']]==['https://example.invalid/1','https://example.invalid/2']
    assert result['read_only'] and not result['eligible_for_render']


def test_invalid_scope_missing_runtime_and_timeout_never_return_empty_success(tmp_path,monkeypatch):
    for start,end in ((0,601),(-1,2),(2,2),(0,float('inf'))):
        with pytest.raises(ValueError):review_subtitles(RAW,[],start,end,runtime=tmp_path)
    with pytest.raises(ValueError,match='尚未安装'):review_subtitles(RAW,[],0,600,runtime=tmp_path)
    (tmp_path/'worker.py').write_text('# isolated')
    def timeout(*args,**kwargs):raise subprocess.TimeoutExpired(args[0],30)
    monkeypatch.setattr(subprocess,'run',timeout)
    with pytest.raises(ValueError,match='未完成'):review_subtitles(RAW,[],0,600,runtime=tmp_path)
