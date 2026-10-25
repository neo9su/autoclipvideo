import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import types

spec = importlib.util.spec_from_file_location('asr_production', Path(__file__).parents[1] / 'scripts/aid_transcribe_recording.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


def test_resume_cached_artifact_submits_once_and_never_changes_business_db(tmp_path, monkeypatch):
    source = tmp_path / 'input.mp4'
    source.write_bytes(b'fixture: metadata is supplied by fake ffprobe')
    db_path = tmp_path / 'business.db'
    with sqlite3.connect(db_path) as db:
        db.execute('create table recordings (id integer, filename text)')
        db.execute("insert into recordings values (7,'input.mp4')")
    before = db_path.read_bytes()
    cfg = tmp_path / 'environment.json'
    cfg.write_text('{}')
    monkeypatch.setattr(worker, 'CONFIG_PATH', cfg)
    monkeypatch.setattr(worker, 'DB_URI', db_path.as_uri() + '?mode=ro')
    monkeypatch.setattr(worker.time, 'sleep', lambda _: None)
    monkeypatch.setitem(sys.modules, 'recording_paths', types.SimpleNamespace(resolve_recording_path=lambda _: str(source)))
    monkeypatch.setattr(worker.subprocess, 'run', lambda *a, **kw: types.SimpleNamespace(
        returncode=0, stdout=json.dumps({'streams': [{'codec_type': 'video', 'width': 1080, 'height': 1920}],
                                        'format': {'duration': 30}}).encode()))
    calls = []

    def request(method, path, body=None):
        calls.append((method, path, body))
        if path == '/v1/profiles':
            return {'douyin-gpu-processing': {'enabled': True}}
        if path == '/v1/snapshot':
            return {'queued': []}
        if method == 'POST':
            return {'id': 99, 'status': 'QUEUED'}
        return {'status': 'SUCCEEDED', 'result': {'srt': '1\n00:00:00,000 --> 00:00:01,000\n这是人生\n', 'segmentCount': 1}}

    monkeypatch.setitem(sys.modules, 'fixture_aid', types.SimpleNamespace(request=request))
    (tmp_path / 'aid_gpu_client.py').write_text('from fixture_aid import request\n')
    (tmp_path / 'recording-7.json').write_text(json.dumps({
        'recording_id': 7, 'artifact_id': 'a' * 32,
        'idempotency_key': 'douyin-recording-7-transcribe-v1'}))
    worker.run(7, tmp_path)
    worker.run(7, tmp_path)
    submissions = [c for c in calls if c[0] == 'POST']
    assert len(submissions) == 1
    assert submissions[0][2]['payload']['douyinGpuRequest']['operation'] == 'transcribe'
    assert json.loads((tmp_path / 'recording-7.json').read_text())['phase'] == 'TRANSCRIBED_NOT_CLIPPED'
    assert db_path.read_bytes() == before
    assert '-->' in (tmp_path / 'recording-7.aid.srt').read_text()
