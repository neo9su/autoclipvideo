"""Run as susun/admin on 203, after checking no active client submission."""
from pathlib import Path
import hashlib
import json
import os
import winreg

SECRET_DIR = Path(r'C:\ProgramData\AIDGPU\douyin-client')
AUDIT = Path(r'C:\Users\neo\douyin_backend\codex_rollbacks\aid-config-20261025')


def run():
    assert os.environ.get('USERNAME', '').lower() == 'susun'
    launcher = Path(r'C:\douyin_login\_uv3.bat')
    report = json.loads((SECRET_DIR / 'install-report.json').read_text())
    assert hashlib.sha256(launcher.read_bytes()).hexdigest() == report['launcher_after_sha256'], 'Launcher changed; reconcile manually'
    before = AUDIT / 'user-env-before.json'
    assert before.exists(), 'Missing user environment backup'
    previous = json.loads(before.read_text())
    temporary = launcher.with_suffix('.aid-rollback')
    temporary.write_bytes((SECRET_DIR / 'uv3-before-aid-20261025.bat').read_bytes())
    os.replace(temporary, launcher)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, 'Environment') as env:
        for name, value in previous.items():
            if value is None:
                try:
                    winreg.DeleteValue(env, name)
                except FileNotFoundError:
                    pass
            else:
                winreg.SetValueEx(env, name, 0, winreg.REG_SZ, value)
    print('Startup/user environment restored; restricted credential files retained')


if __name__ == '__main__':
    run()
