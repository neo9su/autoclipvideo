"""Build the guarded 203 startup-policy deployment. No credentials are exported to stdout."""
from pathlib import Path

def build():
    root=Path(__file__).parents[1]
    guard=(root/'backend/windows_backend_watchdog.py').read_text()
    launcher=(root/'backend/start_windows_backend.ps1').read_text()
    function=launcher[launcher.index('function Get-ActiveSession {'):launcher.index('\nfunction Get-BackendFromOtherSession')]
    return 'GUARD='+repr(guard)+'\nFUNCTION='+repr(function)+'\n'+r'''
from pathlib import Path
import hashlib,json,datetime,os,subprocess,sqlite3
ROOT=Path(r'C:\Users\neo\douyin_backend');GUARD_PATH=Path(r'C:\douyin_login\_wd8899.py');LAUNCHER=ROOT/'backend'/'start_windows_backend.ps1'
INTERACTIVE='DouyinBackend8899SusunInteractive';OBSOLETE=['Uvicorn8899','DouyinBackend8899System','DouyinRemoteBackend8899','DouyinRemoteBackend8899Interactive','Diag8899Susun','Douyin8899User','DouyinBe8899B','Restart8899Interactive'];NAMES=OBSOLETE+[INTERACTIVE,'Wd8899Sys']
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def durable(p,data):
 t=p.with_name(p.name+'.writing')
 with t.open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
 os.replace(t,p)
def ps(code):
 r=subprocess.run(['powershell','-NoProfile','-Command',code],capture_output=True)
 if r.returncode:raise RuntimeError('Scheduled task operation failed: '+str(r.returncode))
 return r.stdout.decode('utf-8-sig').strip()
assert digest(GUARD_PATH)=='ef8d40cfd12b53e40c08f1269b231dd3dbf9d26334b78dde7427286e7d78ee26','Watchdog drift'
assert digest(LAUNCHER)=='063f9cec5ee75ca919d3449e8f6943222afe444072d4cc30fa002d2478940a17','Launcher drift'
with sqlite3.connect(ROOT/'douyin.db') as db:
 assert db.execute("select count(*) from publish_tasks where status='publishing'").fetchone()[0]==0,'Live publish; postpone startup maintenance'
b=ROOT/'codex_rollbacks'/('desktop-startup-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));b.mkdir()
names=','.join("'"+n+"'" for n in NAMES)
state=json.loads(ps("$ErrorActionPreference='Stop';$names=@("+names+"); @($names | ForEach-Object {$t=Get-ScheduledTask -TaskName $_;[pscustomobject]@{name=$t.TaskName;enabled=[bool]$t.Settings.Enabled;running=([string]$t.State -eq 'Running');user=$t.Principal.UserId;logon=[string]$t.Principal.LogonType}}) | ConvertTo-Json -Compress"))
assert len(state)==len(NAMES) and any(x['name']==INTERACTIVE and x['user'].lower()=='susun' and x['logon']=='Interactive' for x in state)
durable(b/'task-state.json',json.dumps(state,indent=2).encode())
for name in NAMES:
 xml=ps("$ErrorActionPreference='Stop';Export-ScheduledTask -TaskName '"+name+"'")
 durable(b/(name+'.xml'),xml.encode('utf-8'))
s=LAUNCHER.read_text(encoding='utf-8-sig');a=s.index('function Get-ActiveSession {');z=s.index('\nfunction Get-BackendFromOtherSession',a);new_launcher=(s[:a]+FUNCTION+'\n'+s[z:]).encode('utf-8-sig')
changes=[(GUARD_PATH,GUARD.encode()),(LAUNCHER,new_launcher)];manifest=[]
for i,(p,data) in enumerate(changes):
 durable(b/str(i),p.read_bytes());manifest.append(dict(target=str(p),backup=str(i),before=digest(p),after=hashlib.sha256(data).hexdigest()))
durable(b/'manifest.json',json.dumps(manifest,indent=2).encode())
rollback=r"""from pathlib import Path
import json,hashlib,subprocess,sqlite3,os
b=Path(__file__).parent;root=b.parents[1]
with sqlite3.connect(root/'douyin.db') as db:assert db.execute("select count(*) from publish_tasks where status='publishing'").fetchone()[0]==0,'Publishing active'
items=json.loads((b/'manifest.json').read_text());states=json.loads((b/'task-state.json').read_text())
for m in items:assert hashlib.sha256(Path(m['target']).read_bytes()).hexdigest()==m['after'],'Source drift'
def ps(s):subprocess.run(['powershell','-NoProfile','-Command',"$ErrorActionPreference='Stop';"+s],check=True,capture_output=True)
ps("Disable-ScheduledTask -TaskName 'Wd8899Sys' | Out-Null")
for m in items:
 p=Path(m['target']);t=p.with_name(p.name+'.restore.tmp');t.write_bytes((b/m['backup']).read_bytes());os.replace(t,p)
xml=str(b/'DouyinBackend8899SusunInteractive.xml').replace("'","''")
ps("Register-ScheduledTask -TaskName 'DouyinBackend8899SusunInteractive' -Xml (Get-Content -LiteralPath '"+xml+"' -Raw -Encoding UTF8) -Force | Out-Null")
for t in states:ps(('Enable' if t['enabled'] else 'Disable')+"-ScheduledTask -TaskName '"+t['name']+"' | Out-Null")
print('Original sources and task configuration restored; existing backend was not stopped.')
"""
durable(b/'rollback.py',rollback.encode())
# Stop the old watchdog before replacing it. No backend or GPU process is killed.
ps("$ErrorActionPreference='Stop';Disable-ScheduledTask -TaskName 'Wd8899Sys' | Out-Null;$t=Get-ScheduledTask -TaskName 'Wd8899Sys';if([string]$t.State -eq 'Running'){Stop-ScheduledTask -TaskName 'Wd8899Sys'}")
try:
 for p,data in changes:durable(p,data)
 compile(GUARD,str(GUARD_PATH),'exec')
 path=str(LAUNCHER).replace("'","''")
 ps("$e=$null;$t=$null;[System.Management.Automation.Language.Parser]::ParseFile('"+path+"',[ref]$t,[ref]$e) | Out-Null;if($e.Count){throw 'Launcher syntax failed'}")
 ps("$ErrorActionPreference='Stop';@("+','.join("'"+n+"'" for n in OBSOLETE)+") | ForEach-Object {Disable-ScheduledTask -TaskName $_ | Out-Null}")
 ps("$ErrorActionPreference='Stop';$t=Get-ScheduledTask -TaskName '"+INTERACTIVE+"';$s=$t.Settings;$s.ExecutionTimeLimit='PT0S';$s.RestartCount=3;$s.RestartInterval='PT1M';$s.StartWhenAvailable=$true;$actions=$t.Actions;if($actions.Count -ne 1){throw 'Unexpected actions'};if($actions[0].Arguments -notmatch '(?i)-WindowStyle'){$actions[0].Arguments='-WindowStyle Hidden '+$actions[0].Arguments};Set-ScheduledTask -TaskName '"+INTERACTIVE+"' -Settings $s -Action $actions | Out-Null;Enable-ScheduledTask -TaskName '"+INTERACTIVE+"' | Out-Null")
 durable(b/'applied.json',json.dumps(dict(applied=True,obsolete_disabled=OBSOLETE,desktop_task=INTERACTIVE)).encode())
finally:
 if next(t for t in state if t['name']=='Wd8899Sys')['enabled']:ps("Enable-ScheduledTask -TaskName 'Wd8899Sys' | Out-Null")
print(json.dumps({'backup':str(b),'applied':True,'backend_restarted':False}))
'''
if __name__=='__main__':print(build())
