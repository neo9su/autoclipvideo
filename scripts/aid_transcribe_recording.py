"""Recover one recording's transcript through AID. Never starts legacy GPU workers."""
import argparse
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import ssl
import subprocess
import sys
import time
import urllib.parse


def save(path, data):
    tmp = path.with_suffix('.writing')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    for attempt in range(12):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 11:
                raise
            time.sleep(.2 * (attempt + 1))


CONFIG_PATH = Path(r'C:\ProgramData\AIDGPU\douyin-client\environment.json')
DB_URI = 'file:C:/Users/neo/douyin_backend/douyin.db?mode=ro'


def run(recording_id, batch):
    batch.mkdir(parents=True, exist_ok=True)
    config = json.loads(CONFIG_PATH.read_text())
    os.environ.update(config)
    spec = importlib.util.spec_from_file_location('aid_client', batch / 'aid_gpu_client.py')
    client = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(client)
    profiles = client.request('GET', '/v1/profiles')
    snapshot = client.request('GET', '/v1/snapshot')
    profile = 'douyin-gpu-processing'
    assert profiles.get(profile, {}).get('enabled'), 'Required profile is unavailable'
    record = batch / f'recording-{recording_id}.json'
    state = json.loads(record.read_text()) if record.exists() else {
        'recording_id': recording_id, 'profile': profile, 'phase': 'preflight',
        'idempotency_key': f'douyin-recording-{recording_id}-transcribe-v1',
        'queue_at_preflight': len(snapshot.get('queued', [])), 'business_db_changed': False}
    state.pop('client_error_type', None)
    try:
        sys.path.insert(0, r'C:\Users\neo\douyin_backend\backend')
        from recording_paths import resolve_recording_path
        with sqlite3.connect(DB_URI, uri=True) as db:
            row = db.execute('select filename from recordings where id=?', (recording_id,)).fetchone()
        assert row, 'Unknown recording'
        resolved = resolve_recording_path(row[0])
        source = Path(resolved) if resolved else None
        assert source and source.is_file(), 'Recording is missing or inaccessible'
        probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                                'stream=codec_type,width,height:format=duration', '-of', 'json', str(source)],
                               capture_output=True, timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        assert probe.returncode == 0, 'Invalid recording container'
        data = json.loads(probe.stdout)
        video = next(s for s in data['streams'] if s.get('codec_type') == 'video')
        assert min(video['width'], video['height']) >= 1080 and max(video['width'], video['height']) >= 1920, 'Below 1080p'
        assert 0 < float(data['format']['duration']) <= 1800, 'Profile requires input at most 1800 seconds'
        state.update(filename=row[0], source=str(source), source_video=data, phase='validated')
        if not state.get('artifact_id'):
            state['phase'] = 'uploading'
            save(record, state)
            url = urllib.parse.urlsplit(config['AID_GPU_MANAGER_URL'])
            key = Path(config['AID_GPU_MANAGER_API_KEY_FILE']).read_text().strip()
            conn = http.client.HTTPSConnection(url.hostname, url.port, context=ssl.create_default_context(
                cafile=config['AID_GPU_MANAGER_CA_FILE']), timeout=600)
            stat = source.stat()
            conn.putrequest('POST', url.path.rstrip('/') + '/v1/artifacts')
            conn.putheader('Authorization', 'Bearer ' + key)
            conn.putheader('Content-Type', 'application/octet-stream')
            conn.putheader('Content-Length', str(stat.st_size))
            conn.putheader('X-File-Name', urllib.parse.quote(source.name))
            conn.endheaders()
            digest = hashlib.sha256()
            with source.open('rb') as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b''):
                    digest.update(chunk)
                    conn.send(chunk)
            response = conn.getresponse()
            artifact = json.load(response)
            conn.close()
            assert response.status == 201, f'Artifact upload HTTP {response.status}'
            assert source.stat().st_size == stat.st_size and source.stat().st_mtime_ns == stat.st_mtime_ns, 'Source changed during upload'
            state.update(artifact_id=artifact['id'], source_sha256=digest.hexdigest(), phase='uploaded')
            save(record, state)
        if not state.get('job_id'):
            request = {'profile': profile, 'idempotencyKey': state['idempotency_key'], 'payload': {
                'douyinGpuRequest': {'operation': 'transcribe', 'inputArtifactId': state['artifact_id'],
                                     'outputFilename': f'recording-{recording_id}.srt', 'language': 'zh'}}}
            save(batch / f'request-{recording_id}.json', request)
            job = client.request('POST', '/v1/jobs', request)
            state.update(job_id=job['id'], phase=job.get('status'), queue_position=job.get('queuePosition'),
                         estimated_start_seconds=job.get('estimatedStartSeconds'),
                         estimated_cold_start_seconds=job.get('estimatedColdStartSeconds'))
            save(record, state)
        while True:
            job = client.request('GET', '/v1/jobs/' + str(state['job_id']))
            state.update(phase=job.get('status'), queue_position=job.get('queuePosition'),
                         assigned_gpu_ids=job.get('assignedGpuIds'), error=job.get('error_message'))
            save(record, state)
            if job.get('status') in {'SUCCEEDED', 'FAILED', 'CANCELLED', 'LOST'}:
                break
            time.sleep(10)
        if job['status'] == 'SUCCEEDED':
            result = job.get('result')
            if isinstance(result, str):
                result = json.loads(result)
            assert isinstance(result, dict) and isinstance(result.get('srt'), str) and '-->' in result['srt'], 'No valid transcript in result'
            output = batch / f'recording-{recording_id}.aid.srt'
            output.write_text(result['srt'], encoding='utf-8')
            state.update(transcript=str(output), segment_count=result.get('segmentCount'),
                         transcript_sha256=hashlib.sha256(output.read_bytes()).hexdigest(), phase='TRANSCRIBED_NOT_CLIPPED')
            save(record, state)
    except BaseException as exc:
        state.update(client_error_type=type(exc).__name__, phase='CLIENT_ERROR')
        save(record, state)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--recording-id', type=int, required=True)
    parser.add_argument('--batch-dir', type=Path, required=True)
    args = parser.parse_args()
    run(args.recording_id, args.batch_dir)
