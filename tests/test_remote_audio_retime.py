"""CPU-only audio/HTTP fixtures: never contact a GPU host."""
import ast
import asyncio
import io
import logging
import os
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace
from typing import Dict, List, Optional
import wave

import pytest

ROOT = Path(__file__).parents[1]


def function_node(path, name):
    tree = ast.parse((ROOT / path).read_text())
    return next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def compile_functions(nodes, env):
    for n in nodes:
        n.decorator_list = []
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), '<audio-fixture>', 'exec'), env)
    return env


def wav_bytes(seconds=1):
    out = io.BytesIO()
    with wave.open(out, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
        w.writeframes(b'\0\0' * int(seconds * 24000))
    return out.getvalue()


@pytest.mark.asyncio
@pytest.mark.parametrize('speed,expected', [(1.0, 1.0), (0.5, 2.0)])
async def test_worker_actual_cpu_ffmpeg(tmp_path, speed, expected):
    source = tmp_path / 'upload.wav'; source.write_bytes(wav_bytes())
    jobs = {'test': {'status': 'queued'}}

    async def ffmpeg(*args):
        assert jobs['test']['status'] == 'processing'
        p = await asyncio.create_subprocess_exec(*args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return await p.wait()

    env = dict(os=os, STORAGE_DIR=str(tmp_path), _audio_concat_jobs=jobs,
               _run_ffmpeg=ffmpeg, logger=logging.getLogger('test'))
    compile_functions([function_node('gpu_service/main.py', '_run_audio_concat_job')], env)
    await env['_run_audio_concat_job']('test', [str(source)], speed)
    assert jobs['test']['status'] == 'done'
    with wave.open(jobs['test']['output_path']) as w:
        duration = w.getnframes() / w.getframerate()
    assert duration == pytest.approx(expected, abs=0.15)
    assert not source.exists()  # uploaded copy only


class Response:
    def __init__(self, status=200, data=None, content=b''):
        self.status, self.data, self.body = status, data, content
        self.content = self
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def json(self): return self.data
    async def iter_chunked(self, _size): yield self.body


class Form:
    def __init__(self): self.fields = []
    def add_field(self, name, value, **kwargs): self.fields.append((name, value))


def client_env(tmp_path, payload, submit=201):
    calls = []
    class Session(Response):
        def post(self, url, data, **kwargs):
            calls.append((url, data.fields))
            return Response(submit, {'job_id': 'test'})
        def get(self, url, **kwargs):
            calls.append((url, None))
            return Response(content=payload) if url.endswith('/audio') else Response(data={'status': 'done'})
    async def sleep(_): pass
    env = dict(os=os, time=time, List=List, Dict=Dict, Optional=Optional,
               asyncio=SimpleNamespace(sleep=sleep), _GPU_SERVICE_URL='http://offline-fixture',
               aiohttp=SimpleNamespace(ClientSession=Session, FormData=Form, ClientTimeout=lambda **kw: kw),
               logger=logging.getLogger('test'))
    compile_functions([function_node('backend/voice_director.py', '_merge_audio_segments'),
                       function_node('backend/voice_director.py', '_probe_duration')], env)
    owner = SimpleNamespace(_output_dir=str(tmp_path))
    owner._probe_duration = lambda path: env['_probe_duration'](owner, path)
    return env, owner, calls


@pytest.mark.asyncio
async def test_single_track_retime_uses_audio_endpoint_preserving_source(tmp_path):
    source = tmp_path / 'input.wav'; source.write_bytes(wav_bytes())
    env, owner, calls = client_env(tmp_path, wav_bytes(2))
    result = await env['_merge_audio_segments'](owner, [{'audio_path': str(source)}], 1, 0.5)
    assert result and Path(result).is_file() and source.exists()
    assert calls[0][0].endswith('/audio-concat-jobs')
    assert ('speed_ratio', '0.5') in calls[0][1]
    assert calls[-1][0].endswith('/audio')
    assert not list(tmp_path.glob('*.download'))


@pytest.mark.asyncio
@pytest.mark.parametrize('payload,submit', [(b'not WAV', 201), (b'', 404)])
async def test_failed_remote_output_preserves_source(tmp_path, payload, submit):
    source = tmp_path / 'input.wav'; source.write_bytes(wav_bytes())
    env, owner, _ = client_env(tmp_path, payload, submit)
    result = await env['_merge_audio_segments'](owner, [{'audio_path': str(source)}], 1, 0.5)
    assert result is None and source.exists()
    assert list(tmp_path.iterdir()) == [source]


@pytest.mark.asyncio
async def test_single_unmodified_track_needs_no_job(tmp_path):
    env, owner, calls = client_env(tmp_path, b'')
    result = await env['_merge_audio_segments'](owner, [{'audio_path': 'original.wav'}], 1)
    assert result == 'original.wav' and calls == []


@pytest.mark.asyncio
async def test_retimed_scene_durations_follow_measured_audio():
    tree = ast.parse((ROOT / 'backend/voice_director.py').read_text())
    branch = next(n for n in ast.walk(tree) if isinstance(n, ast.If)
                  and 'actual_merged_dur < _MIN_AUDIO_DUR' in ast.unparse(n.test))
    code = 'async def fixture(self, audio_segments):\n    is_qianchuan=False\n    actual_merged_dur=16.0\n    _MIN_AUDIO_DUR=30.0\n    group_id=1\n    merged="original.wav"\n    total_duration=16.0\n'
    code += '\n'.join('    ' + line for line in ast.unparse(branch).splitlines())
    code += '\n    return merged,total_duration,audio_segments\n'
    async def merge(_segments, _group, speed_ratio):
        assert speed_ratio == pytest.approx(16 / 30)
        return 'stretched.wav'
    async def duration(_): return 30.0
    owner = SimpleNamespace(_merge_audio_segments=merge, _probe_duration=duration)
    env = dict(logger=logging.getLogger('test'))
    exec(code, env)
    result = await env['fixture'](owner, [{'duration': 10.0}, {'duration': 6.0}])
    assert result[1] == sum(s['duration'] for s in result[2]) == 30.0
