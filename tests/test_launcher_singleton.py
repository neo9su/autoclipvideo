from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from prepare_launcher_singleton_deploy import patch_launcher


def test_scalar_conflict_and_listener_guard_preserve_setup():
    source = (Path(__file__).parents[1] / 'backend/start_windows_backend.ps1').read_text()
    legacy = source.replace('$conflictingProcesses = @(Get-BackendFromOtherSession -SessionId $sessionId)', '$conflictingProcesses = Get-BackendFromOtherSession -SessionId $sessionId').replace('Start-Process -FilePath $Python -WindowStyle Hidden `', 'Start-Process -FilePath $Python `')
    # Remove the new guard to construct the pre-fix fixture.
    start = legacy.index('    # Check the socket too:')
    end = legacy.index('    $conflictingProcesses', start)
    legacy = legacy[:start] + legacy[end:]
    patched = patch_launcher(legacy)
    assert '$conflictingProcesses = @(Get-BackendFromOtherSession -SessionId $sessionId)' in patched
    assert patched.index('Get-NetTCPConnection') < patched.index('Start-Process -FilePath')
    assert '-ErrorAction Stop' in patched
    assert '-WindowStyle Hidden' in patched
    assert 'Stop-Process' not in patched
    assert 'Get-ActiveSession' in patched
    with pytest.raises(RuntimeError, match='drift'):
        patch_launcher(patched)
