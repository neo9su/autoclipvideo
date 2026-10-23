"""Exercise the real polling block without loading speech-model dependencies."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


def test_transient_poll_timeout_keeps_same_job():
    tree = ast.parse(Path('backend/voice_director.py').read_text())
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == '_tts_gpu')
    loop = next(n for n in ast.walk(method) if isinstance(n, ast.While))
    # Remove only the two-second delay from this deterministic unit test.
    loop.body = loop.body[1:]
    wrapper = ast.AsyncFunctionDef(name='run', args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]), body=[loop, ast.Return(ast.Constant(True))], decorator_list=[])
    calls = []
    class Response:
        status = 200
        async def __aenter__(self):
            calls.append('existing-job')
            if len(calls) == 1:
                raise asyncio.TimeoutError()
            return self
        async def __aexit__(self, *args): pass
        async def json(self): return {'status': 'done'}
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def get(self, url, **kwargs):
            assert url.endswith('/tts-jobs/existing-job')
            return Response()
    ns = dict(asyncio=asyncio, aiohttp=SimpleNamespace(ClientSession=Session, ClientTimeout=lambda **kw: None, ClientConnectionError=ConnectionError), time=SimpleNamespace(time=lambda: 0), deadline=10, job_id='existing-job', _GPU_SERVICE_URL='http://worker', logger=Mock(), gpu_tts_timeout=10)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[])), 'poll', 'exec'), ns)
    assert asyncio.run(ns['run']()) is True
    assert len(calls) == 2
