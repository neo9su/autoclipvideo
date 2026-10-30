import asyncio
import subprocess
import sys
import threading
import time
import json

import pytest
from backend.encode_request_runner import run_encode_request
from scripts.patch_director_matcher_nonblocking import patch


def test_large_unicode_request_roundtrip():
    text='假发字幕'*70000
    request=json.dumps({'text':text},ensure_ascii=False)
    code="import json,sys;data=json.load(sys.stdin);print(json.dumps({'length':len(data['text'])}))"
    result=run_encode_request([sys.executable,'-X','utf8','-c',code],request,timeout=5)
    assert result.returncode==0
    assert json.loads(result.stdout)['length']==len(text)


def test_nonreading_child_cannot_block_timeout_with_large_stdin():
    started=time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_encode_request([sys.executable,'-c','import time;time.sleep(10)'],'x'*1048576,timeout=0.2)
    assert time.monotonic()-started<4


def fixture_source():
    # Match the three production anchors; use controlled encoder work only.
    return '''import asyncio
from srt_resolver import resolve_srt_path
async def fallback(_texts):
    try:
        if _texts:
            if True:
                if True:
                    _embs = _encode_subprocess_batch(_texts)
                    return _embs
    except Exception:
        raise

def similarity():
    if True:
        if True:
            result = subprocess.run(
                [_VENV_PYTHON, _ENCODE_SCRIPT],
                input=req + "\\n",
                capture_output=True, text=True, timeout=20,
                encoding="utf-8", errors="replace"
            )
def batch():
    if True:
        if True:
            result = subprocess.run(
                [_VENV_PYTHON, _ENCODE_SCRIPT],
                input=req + "\\n",
                capture_output=True, text=True, timeout=20,
                encoding="utf-8", errors="replace"
            )
'''


def test_async_fallback_yields_while_encoder_waits():
    source=patch(fixture_source())
    source=source.replace('from srt_resolver import resolve_srt_path','').replace('from encode_request_runner import run_encode_request','')
    entered=threading.Event();release=threading.Event()
    def encoder(texts):
        entered.set()
        assert release.wait(timeout=2), 'Main event loop was blocked by the encoder'
        return [1]
    scope={'_encode_subprocess_batch':encoder};exec(source,scope)
    async def scenario():
        task=asyncio.create_task(scope['fallback'](['test']))
        try:
            for _ in range(100):
                if entered.is_set():break
                await asyncio.sleep(0.005)
            assert entered.is_set() and not task.done()
            release.set()
            assert await task==[1]
        finally:release.set()
    asyncio.run(scenario())


def test_patch_refuses_repeat_and_drift():
    source=fixture_source()
    assert patch(source).count('result = run_encode_request(')==2
    with pytest.raises(ValueError):patch(patch(source))
    with pytest.raises(ValueError):patch(source.replace('input=req +','input=changed +',1))
