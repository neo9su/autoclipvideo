"""203 admin verification: one idle backend restart through the desktop watchdog."""
from pathlib import Path
import importlib.util,sqlite3,subprocess,time,json,psutil,urllib.request,os
ROOT=Path(r'C:\Users\neo\douyin_backend')
TASK='DouyinBackend8899SusunInteractive'

def run(backup):
    b=ROOT/'codex_rollbacks'/backup
    spec=importlib.util.spec_from_file_location('desktop_guard',r'C:\douyin_login\_wd8899.py');guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
    with sqlite3.connect(ROOT/'douyin.db') as db:
        assert db.execute("select count(*) from publish_tasks where status='publishing'").fetchone()[0]==0,'Live publication; verification postponed'
    before=guard.listeners();assert len(before)==1
    old=psutil.Process(before[0]);created=old.create_time();old_session=guard.process_session(old.pid)
    assert old_session>0 and old.username().lower().split('\\')[-1]=='susun','Unexpected current backend owner'
    report=dict(before_pid=old.pid,before_session=old_session,normal_guard_result=guard.run_once(),phase='prepared')
    (b/'recovery-verification.json').write_text(json.dumps(report,indent=2))
    try:
        r=subprocess.run(['powershell','-NoProfile','-Command',"$ErrorActionPreference='Stop';Stop-ScheduledTask -TaskName '"+TASK+"'"],capture_output=True);assert r.returncode==0,'Cannot stop the desktop supervisor'
        for _ in range(10):
            if not psutil.pid_exists(old.pid):break
            time.sleep(1)
        if psutil.pid_exists(old.pid):
            with sqlite3.connect(ROOT/'douyin.db') as db:assert db.execute("select count(*) from publish_tasks where status='publishing'").fetchone()[0]==0
            process=psutil.Process(old.pid);assert process.create_time()==created
            process.terminate();process.wait(timeout=15)
        assert not guard.listeners(),'Unexpected remaining backend listener'
        result=guard.run_once(miss_limit=1);assert result=='desktop-requested',result
        report['watchdog_recovery_result']=result
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            pids=guard.listeners()
            if len(pids)==1 and guard.healthy():
                report.update(after_pid=pids[0],after_session=guard.process_session(pids[0]),phase='recovered')
                assert pids[0]!=old.pid and report['after_session']==old_session and report['after_session']>0
                break
            time.sleep(2)
        else:raise RuntimeError('Desktop recovery did not become healthy')
        # Allow a repeated supervisor iteration before declaring the owner stable.
        time.sleep(20)
        assert guard.listeners()==[report['after_pid']] and guard.process_session(report['after_pid'])==old_session
        report['repeat_guard_result']=guard.run_once();assert report['repeat_guard_result']=='healthy'
        report['phase']='verified'
    finally:
        # Always preserve the desktop supervisor, even when verification fails.
        subprocess.run(['schtasks','/Run','/TN',TASK],capture_output=True,timeout=30)
        p=b/'recovery-verification.json';t=p.with_name(p.name+'.writing')
        with t.open('wb') as f:f.write(json.dumps(report,indent=2).encode());f.flush();os.fsync(f.fileno())
        os.replace(t,p)
    print(json.dumps(report),flush=True)

if __name__=='__main__':
    import sys
    run(sys.argv[1])
