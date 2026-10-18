import ast
from pathlib import Path
import os
from types import SimpleNamespace

import pytest

SOURCE=Path(__file__).parents[1]/'backend/main.py'


class HTTPException(Exception):
    def __init__(self,status_code,detail): self.status_code=status_code


class Result:
    async def __aenter__(self): return self
    async def __aexit__(self,*args): pass
    async def fetchone(self): return {'clip_filename':'room/new.mp4','clipped':2}
    def execute(self,*args): return self


@pytest.mark.asyncio
@pytest.mark.parametrize('route', ['download_clip','download_recording_clip'])
@pytest.mark.parametrize('current_exists,legacy_exists', [(True,False),(False,True),(True,True),(False,False)])
async def test_download_resolves_configured_storage_then_legacy(tmp_path,route,current_exists,legacy_exists):
    current=tmp_path/'current';legacy=tmp_path/'project'/'recordings'
    (tmp_path/'project/backend').mkdir(parents=True)
    for root,exists in [(current,current_exists),(legacy,legacy_exists)]:
        (root/'room').mkdir(parents=True)
        if exists:(root/'room/new.mp4').write_bytes(b'fixture')
    tree=ast.parse(SOURCE.read_text())
    nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))
           and n.name in ('_recording_file_path',route)]
    for n in nodes:n.decorator_list=[]
    env=dict(os=os,RECORDINGS_DIR=str(current),__file__=str(tmp_path/'project/backend/main.py'),
             aio_connect=Result,aiosqlite=SimpleNamespace(Row=None),HTTPException=HTTPException,
             FileResponse=lambda path,**kwargs:Path(path).resolve())
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE),'exec'),env)
    if not current_exists and not legacy_exists:
        with pytest.raises(HTTPException) as error:await env[route](1)
        assert error.value.status_code==404
    else:
        result=await env[route](1)
        assert result==(current/'room/new.mp4' if current_exists else legacy/'room/new.mp4').resolve()
