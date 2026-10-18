from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from prepare_windows_launcher_deploy import patch_launcher, CONFLICT_FUNCTION, WATCH_LOOP


def legacy():
    return '''# preserve environment, logging, and launch options
function Stop-BackendFromOtherSession {
    Stop-Process -Id $process.ProcessId -Force
}
while ($true) {
    Stop-BackendFromOtherSession -SessionId $sessionId
    $env:STORAGE_DIR = 'F:\\douyin_recordings'
    Start-Process -FilePath $Python
        while (-not $backend.HasExited) {
            if ($null -eq $activeSessionId) {
                Stop-Process -Id $backend.Id -Force
            }
        }
}
'''


@pytest.mark.parametrize('blank_lines',[False,True])
def test_both_legacy_policies_removed_without_changing_launch_setup(blank_lines):
    old=legacy()
    if blank_lines:old=old.replace('\n','\n\n')
    new=patch_launcher(old)
    assert 'Stop-Process' not in new
    assert CONFLICT_FUNCTION in new and WATCH_LOOP in new
    assert "$env:STORAGE_DIR = 'F:\\douyin_recordings'" in new
    assert 'Start-Process -FilePath $Python' in new
    assert 'Start-Sleep -Seconds 15' in new


def test_already_fixed_or_unknown_launcher_is_rejected():
    with pytest.raises(RuntimeError,match='session-kill policy'):
        patch_launcher(patch_launcher(legacy()))
    with pytest.raises(RuntimeError,match='Unhandled destructive'):
        patch_launcher(legacy()+'\nStop-Process -Id 999\n')


def test_repository_launcher_contains_no_forced_session_shutdown():
    source=(Path(__file__).parents[1]/'backend/start_windows_backend.ps1').read_text()
    assert 'Stop-Process' not in source
    assert WATCH_LOOP in source
    assert 'Get-BackendFromOtherSession -SessionId $sessionId' in source
