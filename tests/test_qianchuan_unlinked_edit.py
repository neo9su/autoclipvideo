"""Exercise orchestration only: no model, media job or publishing calls."""
import ast
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest


@pytest.mark.parametrize('score_ok,review_hold,should_compose',[
    (True,False,True),(False,False,False),(True,True,False)])
def test_unlinked_product_does_not_block_edit_but_matching_still_applies(monkeypatch,score_ok,review_hold,should_compose):
    source=(Path(__file__).parents[1]/'backend/api_v2.py').read_text()
    names={'_loads_qianchuan_json','_saved_qianchuan_resume','_run_qianchuan_pipeline'}
    nodes=[n for n in ast.parse(source).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in names]
    writes=[];composed=[];loaded=[]
    class DB:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def execute(self,sql,args):writes.append((sql,args))
        async def commit(self):pass
    async def claim(*args,**kwargs):return True
    async def hold(*args):return review_hold
    product={'id':740,'product_name':'same name','product_url':''}
    saved={'preview_mode':False,'product_context':product,'scenes':[{'voiceover_text':'original'}]}
    async def load(path,group_id,product_id=None):
        loaded.append(product_id)
        return {'group':{'label':'known hairstyle','qianchuan_script':json.dumps(saved)}}
    async def compose(group_id,script):composed.append(script)
    monkeypatch.setitem(sys.modules,'db',SimpleNamespace(DB_PATH='unused',aio_connect=lambda:DB()))
    monkeypatch.setitem(sys.modules,'pipeline_state',SimpleNamespace(claim_pipeline_start=claim))
    monkeypatch.setitem(sys.modules,'aiosqlite',SimpleNamespace(connect=lambda _:DB()))
    ns={'Dict':dict,'Optional':__import__('typing').Optional,'Any':object,'json':json,
        'logger':Mock(),'load_group_context':load,'hold_for_review':hold,
        'score_product_match':lambda *args,**kwargs:{'ok':score_ok,'product':product,'identity':{'ok':True}},
        '_qianchuan_generate_bg':compose,'generate_qianchuan_script':Mock(side_effect=AssertionError('Saved script must survive'))}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'<pipeline-fixture>','exec'),ns)
    asyncio.run(ns['_run_qianchuan_pipeline'](1))
    assert loaded==[None,'740']
    assert bool(composed)==should_compose
    if should_compose:
        assert composed[0]==saved
        assert any('qianchuan_script=?' in sql for sql,_ in writes)
    elif not review_hold:
        assert any('qianchuan_status=-1' in sql for sql,_ in writes)
