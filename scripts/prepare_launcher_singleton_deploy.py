"""Preserve remote setup while fixing PowerShell scalar enumeration and console storms."""
import inspect
from pathlib import Path
from prepare_windows_launcher_deploy import build as previous_build
from prepare_2k_deploy import raw_replacements


def patch_launcher(source):
    old = '$conflictingProcesses = Get-BackendFromOtherSession -SessionId $sessionId'
    if source.count(old) != 1:
        raise RuntimeError('Conflict assignment drift')
    source = source.replace(old, '$conflictingProcesses = @(Get-BackendFromOtherSession -SessionId $sessionId)')
    anchor = '    $conflictingProcesses = @('
    check = '''    # Check the socket too: another account's command line may be inaccessible.
    $listeners = @(Get-NetTCPConnection -State Listen -ErrorAction Stop | Where-Object { $_.LocalPort -eq $Port })
    if ($listeners.Count -gt 0) {
        Start-Sleep -Seconds 15
        continue
    }
'''
    source = source.replace(anchor, check + anchor, 1)
    old = 'Start-Process -FilePath $Python `'
    if source.count(old) != 1:
        raise RuntimeError('Start-Process drift')
    source = source.replace(old, 'Start-Process -FilePath $Python -WindowStyle Hidden `')
    return source


def build():
    body = previous_build().split('from pathlib import Path\nimport datetime', 1)[1]
    body = 'from pathlib import Path\nimport datetime' + body
    body = body.replace('launcher-session-policy-', 'launcher-singleton-')
    return 'import difflib\n' + inspect.getsource(raw_replacements) + '\n' + inspect.getsource(patch_launcher) + '\n' + body


if __name__ == '__main__':
    print(build())
