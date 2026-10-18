"""Patch only destructive launcher policies; preserve production environment/setup."""
import inspect
from pathlib import Path
import re
from prepare_2k_deploy import raw_replacements

WATCH_LOOP = '''        while (-not $backend.HasExited) {
            # Session discovery must never terminate in-flight backend work.
            Start-Sleep -Seconds 10
            $backend.Refresh()
        }'''
CONFLICT_FUNCTION = '''function Get-BackendFromOtherSession {
    param([int]$SessionId)
    $processes = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'"
    return @($processes | Where-Object {
        $_.CommandLine -and $_.CommandLine -match $backendProcessPattern -and $_.SessionId -ne $SessionId
    })
}'''
CONFLICT_CHECK = '''    $conflictingProcesses = Get-BackendFromOtherSession -SessionId $sessionId
    if ($conflictingProcesses.Count -gt 0) {
        Write-Warning "Another backend session is running; waiting without stopping it."
        Start-Sleep -Seconds 15
        continue
    }'''


def patch_launcher(source):
    if source.count('while (-not $backend.HasExited) {') != 1:
        raise RuntimeError('Launcher child monitor drift')
    pattern = r'^        while \(-not \$backend.HasExited\) \{\n.*?^        \}'
    match = re.search(pattern, source, re.M | re.S)
    if not match or 'Stop-Process -Id $backend.Id -Force' not in match[0]:
        raise RuntimeError('Expected session-kill policy missing; inspect first')
    source = source[:match.start()] + WATCH_LOOP + source[match.end():]
    if 'function Stop-BackendFromOtherSession {' in source:
        source, count = re.subn(r'^function Stop-BackendFromOtherSession \{\n.*?^\}',
                               lambda _: CONFLICT_FUNCTION, source, flags=re.M | re.S)
        if count != 1:
            raise RuntimeError('Cross-session function drift')
        source, count = re.subn(r'^    Stop-BackendFromOtherSession -SessionId \$sessionId\s*$',
                               lambda _: CONFLICT_CHECK, source, flags=re.M)
        if count != 1:
            raise RuntimeError('Cross-session call drift')
    if 'Stop-Process' in source or 'Stop-BackendFromOtherSession' in source:
        raise RuntimeError('Unhandled destructive launcher command')
    if 'Get-BackendFromOtherSession -SessionId $sessionId' not in source:
        raise RuntimeError('Expected listener conflict check missing')
    return source


def build():
    setup = 'import re,difflib\n' + '\n'.join(
        name+' = '+repr(globals()[name])+'\n' for name in
        ['WATCH_LOOP','CONFLICT_FUNCTION','CONFLICT_CHECK'])
    setup += inspect.getsource(raw_replacements)+'\n'+inspect.getsource(patch_launcher)+'\n'
    return setup+r'''
from pathlib import Path
import datetime,hashlib,json,os,subprocess
p=Path(r'C:\Users\neo\douyin_backend\backend\start_windows_backend.ps1')
old=p.read_bytes();raw=old.decode('utf-8');patched=patch_launcher(raw.replace('\r\n','\n'))
for before,after in raw_replacements(raw,patched):
 assert raw.count(before)==1
 raw=raw.replace(before,after)
new=raw.encode('utf-8')
tmp=p.with_suffix('.codex-preflight.ps1');tmp.write_bytes(new)
try:
 cmd="$errors=$null; $tokens=$null; [System.Management.Automation.Language.Parser]::ParseFile('"+str(tmp)+"',[ref]$tokens,[ref]$errors)|Out-Null; if($errors.Count){exit 1}"
 subprocess.run(['powershell','-NoProfile','-Command',cmd],capture_output=True,check=True)
finally:tmp.unlink(missing_ok=True)
backup=p.parents[1]/'codex_rollbacks'/('launcher-session-policy-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir();(backup/'launcher.before').write_bytes(old)
m=dict(target=str(p),before=hashlib.sha256(old).hexdigest(),after=hashlib.sha256(new).hexdigest())
(backup/'manifest.json').write_text(json.dumps(m,indent=2))
(backup/'rollback.py').write_text("""from pathlib import Path
import json,hashlib,os
b=Path(__file__).parent;m=json.loads((b/'manifest.json').read_text());p=Path(m['target'])
assert hashlib.sha256(p.read_bytes()).hexdigest() in (m['before'],m['after']), 'Source drift'
old=(b/'launcher.before').read_bytes();assert hashlib.sha256(old).hexdigest()==m['before']
t=p.with_suffix('.rollback.tmp');t.write_bytes(old);os.replace(t,p)
print('Launcher restored. Existing PowerShell process needs controlled restart to load it. No database restored.')
""")
assert p.read_bytes()==old, 'Source drift'
tmp=p.with_suffix('.codex.tmp');tmp.write_bytes(new);os.replace(tmp,p)
print(json.dumps(dict(backup=str(backup),manifest=m,activation_required=True)))
'''


if __name__ == '__main__':
    print(build())
