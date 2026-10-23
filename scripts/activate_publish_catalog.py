"""203 admin activation; never interrupts a live publishing task or restarts GPU."""
from pathlib import Path
import importlib.util,json,sqlite3,subprocess,sys
import psutil


def main(backup_name):
    root=Path(r'C:\Users\neo\douyin_backend')
    with sqlite3.connect(root/'douyin.db') as db:
        assert db.execute("select count(*) from publish_tasks where status='publishing'").fetchone()[0]==0, 'Live publishing task; postpone activation'
    p=root/'codex_operations'/'activate_remote_audio.py'
    spec=importlib.util.spec_from_file_location('activation',p);tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)
    original=tool.subprocess.run
    def checked_run(args,**kwargs):
        try:return original(args,**kwargs)
        except subprocess.CalledProcessError:
            # schtasks /End may finish the captured process before taskkill runs.
            # Accept only a proven absent PID; permission errors on live processes propagate.
            if args[:2]==['taskkill','/PID'] and not psutil.pid_exists(int(args[2])):
                return subprocess.CompletedProcess(args,0)
            raise
    tool.subprocess.run=checked_run
    expected={Path(x['target']):x['after'] for x in json.loads((root/'codex_rollbacks'/backup_name/'manifest.json').read_text())}
    tool.main(expected=expected,rollback_order=[backup_name],label='publish-catalog-activation',restart_worker=False,backend_owner='Uvicorn8899')


if __name__=='__main__':main(sys.argv[1])
