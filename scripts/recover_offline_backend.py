"""Explicit 203 incident recovery: only known backend processes, never GPU workers."""
from pathlib import Path
import datetime
import hashlib
import importlib.util
import json
import sqlite3
import time

ROOT=Path(r'C:\Users\neo\douyin_backend')


def main():
    import psutil
    path=ROOT/'codex_operations'/'activate_remote_audio.py'
    assert hashlib.sha256(path.read_bytes()).hexdigest()=='f851ebc39ebc771e5dac9a36f80684c18ea44c54436b711d41391327db81b87e'
    spec=importlib.util.spec_from_file_location('maintenance',path)
    tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)
    if tool.backend_pids():
        raise RuntimeError('Backend is listening again; use normal maintenance instead')
    plan=tool.backend_task_plan('Uvicorn8899')
    processes=[]
    for p in psutil.process_iter(['pid','name','cmdline','create_time']):
        args=p.info['cmdline'] or []
        if (p.info['name'] or '').lower()!='python.exe':continue
        if 'uvicorn' not in args or 'main:app' not in args or '8899' not in args:continue
        if Path(p.cwd()).resolve()!=(ROOT/'backend').resolve():
            raise RuntimeError('Unexpected backend checkout; inspect before recovery')
        processes.append({'pid':p.pid,'created':p.create_time()})
    if not processes:raise RuntimeError('No known stalled backend processes; inspect first')
    gpu=tool.request(8877,'/health')
    backup=ROOT/'codex_rollbacks'/('offline-backend-recovery-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    backup.mkdir()
    (backup/'task-state.json').write_text(json.dumps(plan,indent=2))
    (backup/'restore_tasks.py').write_text(tool.TASK_RECOVERY)
    with sqlite3.connect(ROOT/'douyin.db') as db:
        with sqlite3.connect(backup/'douyin.db.snapshot') as target:db.backup(target)
    journal=dict(phase='backed_up',processes=processes,gpu_pid_before=gpu['pid'],
                 gpu_active_before=gpu.get('media_jobs_active'),task_plan=plan,
                 database_restore='never automatic',code_version='8bf7508')
    def record(phase):
        journal['phase']=phase
        (backup/'recovery.json').write_text(json.dumps(journal,indent=2))
        print(json.dumps({'phase':phase,'backup':str(backup)}),flush=True)
    changed=[];ready=False
    record('backed_up')
    try:
        tool.pause_backend_tasks(plan,changed)
        record('supervisors_paused')
        for item in processes:
            try:
                p=psutil.Process(item['pid'])
                if p.create_time()!=item['created']:raise RuntimeError('PID was reused')
                p.kill();p.wait(timeout=20)
            except psutil.NoSuchProcess:pass
        assert not tool.backend_pids(), 'Unexpected listener started; inspect'
        tool.task_action('Enable',plan['restart_task'])
        tool.task_action('Run',plan['restart_task'])
        tool.wait_health(8899,seconds=180)
        ready=True
        tool.restore_backend_tasks(plan,changed)
        assert tool.request(8877,'/health')['pid']==gpu['pid']
        journal['backend_pids_after']=sorted(tool.backend_pids())
        record('complete')
    finally:
        if not ready:
            try:tool.restore_backend_tasks(plan,changed)
            except Exception as error:
                journal['restore_error']=type(error).__name__;record('restore_failed')
                raise
            record('backend_restored_after_error')


if __name__=='__main__':main()
