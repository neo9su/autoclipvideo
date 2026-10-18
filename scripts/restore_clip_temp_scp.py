"""Restore a single archived intermediate job via the authorized 220 SSH relay."""
import argparse
import json
import shlex
import subprocess


def restore(job,archive,admin,destination_root=r'F:\douyin_recordings\clips'):
    if len(job)!=16 or any(c not in '0123456789abcdef' for c in job):raise ValueError('Invalid job')
    code='JOB='+repr(job)+'\nARCHIVE='+repr(archive)+'\nADMIN='+repr(admin)+'\nDESTINATION_ROOT='+repr(destination_root)+'\n'+r'''
import subprocess,json,shlex

def win(code):
 r=subprocess.run(['ssh','-o','BatchMode=yes','dyy',r'C:\Python313\python.exe -X utf8 -'],input=code,text=True,capture_output=True,check=True);return r.stdout
r=subprocess.run(['ssh','-o','BatchMode=yes','neo@10.190.0.222','cat '+shlex.quote(ARCHIVE+'/'+JOB+'/manifest.json')],capture_output=True,text=True,check=True)
plan=json.loads(r.stdout);assert plan['job_id']==JOB
stage=ADMIN+'\\restore-scp-stage\\'+JOB
win('import pathlib\np=pathlib.Path('+repr(stage)+');p.mkdir(parents=True,exist_ok=False)')
sources=['neo@10.190.0.222:'+ARCHIVE+'/'+JOB+'/'+f['name'] for f in plan['files']]+['neo@10.190.0.222:'+ARCHIVE+'/'+JOB+'/manifest.json']
# Copy into a new staging directory, then let the checked restore implementation
# reject any existing production files. SCP never targets production here.
dest='dyy:'+stage.replace(chr(92),'/')+'/'
subprocess.run(['scp','-3','-B','-p',*sources,dest],check=True)
result=win('import sys,json\nsys.path.insert(0,'+repr(ADMIN)+')\nimport archive_clip_temps as m\nprint(json.dumps({"restored_files":m.restore('+repr(DESTINATION_ROOT)+','+repr(stage)+')}))')
print(result.strip())
'''
    result=subprocess.run(['ssh','-o','BatchMode=yes','claw@10.190.0.220','.hermes/hermes-agent/venv/bin/python -'],input=code,text=True,capture_output=True,check=True)
    return json.loads(result.stdout)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('job');p.add_argument('--archive',required=True);p.add_argument('--admin',required=True);a=p.parse_args()
    print(json.dumps(restore(a.job,a.archive,a.admin)))
