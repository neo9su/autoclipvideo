"""Restore one archived job from 222 to 203 without overwriting local files."""
import argparse
import base64
import json
import shlex
import subprocess


def windows_command(code):
    encoded=base64.b64encode(code.encode()).decode()
    command='C:\\Python313\\python.exe -X utf8 -c "import base64;exec(base64.b64decode(\''+encoded+'\'))"'
    bridge='import subprocess,sys;raise SystemExit(subprocess.run('+repr(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=8','dyy',command])+',stdin=sys.stdin.buffer).returncode)'
    return ['ssh','-o','BatchMode=yes','claw@10.190.0.220','.hermes/hermes-agent/venv/bin/python -c '+shlex.quote(bridge)]


def restore_job(job,archive,admin):
    if len(job)!=16 or any(c not in '0123456789abcdef' for c in job):raise ValueError('Invalid job')
    sender=f"import sys,json;from pathlib import Path;sys.path.insert(0,{archive!r});import archive_clip_temps as m;p=json.loads((Path({archive!r})/{job!r}/'manifest.json').read_text());m.send({archive!r},p,sys.stdout.buffer)"
    stage=admin+'\\restore-stage'
    receiver=f"import sys,json;sys.path.insert(0,{admin!r});import archive_clip_temps as m;print(json.dumps(m.receive({stage!r},sys.stdin.buffer)))"
    source=subprocess.Popen(['ssh','-o','BatchMode=yes','neo@10.190.0.222','python3 -c '+shlex.quote(sender)],stdout=subprocess.PIPE)
    sink=subprocess.run(windows_command(receiver),stdin=source.stdout,capture_output=True,timeout=900)
    source.stdout.close();source.wait(timeout=30)
    if source.returncode or sink.returncode:raise RuntimeError('Restore transfer failed; archive retained')
    archive_job=stage+'\\'+job
    restore=f"import sys,json;sys.path.insert(0,{admin!r});import archive_clip_temps as m;print(json.dumps({{'restored_files':m.restore(r'F:\\douyin_recordings\\clips',{archive_job!r})}}))"
    result=subprocess.run(windows_command(restore),capture_output=True,check=True,timeout=900)
    return json.loads(result.stdout)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('job');p.add_argument('--archive',required=True);p.add_argument('--admin',required=True);a=p.parse_args()
    print(json.dumps(restore_job(a.job,a.archive,a.admin)))
