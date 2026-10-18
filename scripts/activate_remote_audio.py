"""Explicit 203 administrative maintenance: preserve work, activate staged code.

No new media jobs are submitted. Existing backend startup recovery requeues interrupted
control-plane tasks. Persistent worker queues and recent director jobs must drain first.
"""
from pathlib import Path
import datetime
import hashlib
import json
import re
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request

ROOT = Path(r'C:\Users\neo\douyin_backend')
WORKER = Path(r'C:\Users\neo\douyin_processor')
EXPECTED = {
    ROOT / 'backend' / 'voice_director.py': 'e80730f31d11120b819b85082e3c226b1e1496898b8c1a85e4807a1eee19e632',
    ROOT / 'gpu_service' / 'main.py': '7254dd1b8ccfbf8903845a148315882d1c8abdabb639e216399c49a53a74c18a',
    WORKER / 'gpu_service' / 'main.py': '7254dd1b8ccfbf8903845a148315882d1c8abdabb639e216399c49a53a74c18a',
}


def request(port, path, method='GET', timeout=15):
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}',
                                 data=b'' if method == 'POST' else None, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def director_ids():
    ids = set()
    for filename in [WORKER / 'gpu_service_stdout.log', WORKER / 'gpu_service_stderr.log',
                     Path(r'C:\douyin_login\_uv3.log')]:
        with filename.open('rb') as stream:
            stream.seek(max(0, filename.stat().st_size - 1000000))
            ids.update(re.findall(rb'dir_[0-9a-f]{12}', stream.read()))
    return {value.decode() for value in ids}


def assert_worker_idle(ids):
    health = request(8877, '/health')
    fields = ['gpu_busy', 'queue_depth', 'clip_jobs_running', 'clip_jobs_pending',
              'concat_jobs_active', 'classic_concat_jobs_active']
    if any(k not in health or health[k] for k in fields):
        raise RuntimeError('Worker health counters not idle')
    if any(health.get('media_jobs_active', {}).values()):
        raise RuntimeError('Worker complete media counters not idle')
    with sqlite3.connect(r'F:\douyin_recordings\jobs.db') as db:
        for table in ['jobs', 'clip_jobs', 'tts_jobs', 'concat_jobs']:
            n = db.execute("select count(*) from " + table +
                           " where status is null or status not in ('done','error','cancelled','canceled')").fetchone()[0]
            if n:
                raise RuntimeError('Worker queue active: ' + table)
    for job_id in ids:
        try:
            job = request(8877, '/director-jobs/' + job_id, timeout=5)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                continue
            raise
        if job.get('status') not in ('done', 'error', 'cancelled', 'canceled'):
            raise RuntimeError('Director task still active')
    return health


def backend_pids():
    cmd = "Get-NetTCPConnection -LocalPort 8899 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique"
    result = subprocess.run(['powershell', '-NoProfile', '-Command', cmd], capture_output=True, text=True)
    return {int(value) for value in result.stdout.split() if value.isdigit()}


def wait_health(port, required=None, seconds=90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            health = request(port, '/health', timeout=3)
            if required is None or required(health):
                return health
        except (OSError, ValueError):
            pass
        time.sleep(3)
    raise RuntimeError(f'Service readiness timeout: {port}')


def main():
    for path, digest in EXPECTED.items():
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError('Source drift; no maintenance action')
    if request(8899, '/api/gpu/status').get('maintenance') is not False:
        raise RuntimeError('Existing maintenance state must be preserved; no action')
    before_gpu = assert_worker_idle(director_ids())
    backup = ROOT / 'codex_rollbacks' / ('audio-activation-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    backup.mkdir()
    with sqlite3.connect(ROOT / 'douyin.db') as db:
        db.row_factory = sqlite3.Row
        active = [dict(row) for row in db.execute('select id,director_status,creative_status,qianchuan_status,classic_status from clip_groups where director_status=1 or creative_status=1 or qianchuan_status=1 or classic_status=1')]
        with sqlite3.connect(backup / 'douyin.db.snapshot') as snapshot:
            db.backup(snapshot)
    journal = dict(backup=str(backup), gpu_pid_before=before_gpu['pid'],
                   interrupted_control_plane_groups=active, phase='backed_up',
                   database_restore='never automatic', rollback_order=['remote-audio-20261018-162521', 'remote-audio-20261018-162339'])
    def record(phase):
        journal['phase'] = phase
        (backup / 'activation.json').write_text(json.dumps(journal, indent=2), encoding='utf-8')
        print(json.dumps({'phase': phase, 'backup': str(backup)}), flush=True)
    record('backed_up')
    stopped = False
    maintenance = False
    worker_restarted = False
    try:
        request(8899, '/api/gpu/maintenance', 'POST')
        maintenance = True
        assert_worker_idle(director_ids())
        pids = backend_pids()
        if len(pids) != 1:
            raise RuntimeError('Expected exactly one backend listener')
        stopped = True  # Ensure startup recovery also runs if stopping fails part-way.
        subprocess.run(['schtasks', '/End', '/TN', 'Uvicorn8899'], capture_output=True)
        for pid in pids & backend_pids():
            subprocess.run(['taskkill', '/PID', str(pid), '/F'], capture_output=True, check=True)
        record('backend_paused')
        # A last submission may have raced the maintenance flag. Drain it instead of killing it.
        deadline = time.monotonic() + 120
        while True:
            try:
                assert_worker_idle(director_ids())
                break
            except RuntimeError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(5)
        record('worker_drained')
        result = request(8878, '/restart/gpu', 'POST', timeout=20)
        if result.get('ok') is not True:
            raise RuntimeError('Watchdog did not confirm restart')
        worker_restarted = True
        health = wait_health(8877, lambda value: value.get('pid') != before_gpu['pid'] and 'media_jobs_active' in value)
        journal['gpu_pid_after'] = health['pid']
        schema = request(8877, '/openapi.json')
        ref = schema['paths']['/audio-concat-jobs']['post']['requestBody']['content']['multipart/form-data']['schema']['$ref'].split('/')[-1]
        speed = schema['components']['schemas'][ref]['properties']['speed_ratio']
        if speed.get('minimum') != 0.5 or speed.get('maximum') != 2.0:
            raise RuntimeError('New audio API speed constraints not loaded')
        record('worker_updated')
    finally:
        if stopped:
            subprocess.run(['schtasks', '/Run', '/TN', 'Uvicorn8899'], capture_output=True, check=True)
            wait_health(8899)
            record('backend_restored' if not worker_restarted else 'services_started')
        elif maintenance:
            request(8899, '/api/gpu/maintenance', 'DELETE')
    # Maintenance is memory-local and resets at restart; preserve the normal operational state.
    status = request(8899, '/api/gpu/status')
    if status.get('maintenance') is True:
        request(8899, '/api/gpu/maintenance', 'DELETE')
    record('complete')
    print(json.dumps({'complete': True, 'gpu_pid': journal['gpu_pid_after'],
                      'interrupted_control_plane_groups': len(active)}), flush=True)


if __name__ == '__main__':
    main()
