import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('prepare_audio', ROOT / 'scripts/prepare_remote_audio_deploy.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


def runner(tmp_path):
    body = prepare.build().split('\n', 1)[1]
    backup_root = tmp_path / 'backups'; backup_root.mkdir()
    return body.replace("Path(r'C:\\Users\\neo\\douyin_backend\\codex_rollbacks')", f'Path({str(backup_root)!r})'), backup_root


def test_backup_and_conditional_rollback_preserve_crlf(tmp_path):
    target = tmp_path / 'fixture.py'
    original = b'def f():\r\n    return 1\r\n'
    target.write_bytes(original)
    body, backup_root = runner(tmp_path)
    exec(body, {'PLAN': [(str(target), [('return 1', 'return 2')])]})
    assert target.read_bytes() == original.replace(b'return 1', b'return 2')
    rollback = next(backup_root.glob('*/rollback.py'))
    exec(rollback.read_text(), {'__file__': str(rollback)})
    assert target.read_bytes() == original
    target.write_text('user change')
    with pytest.raises(AssertionError):
        exec(rollback.read_text(), {'__file__': str(rollback)})
    assert target.read_text() == 'user change'


def test_preflight_failure_changes_no_files(tmp_path):
    target = tmp_path / 'fixture.py'; target.write_text('value=1\n')
    body, backup_root = runner(tmp_path)
    with pytest.raises(RuntimeError):
        exec(body, {'PLAN': [(str(target), [('missing text', 'anything')])]})
    assert target.read_text() == 'value=1\n'
    assert list(backup_root.iterdir()) == []
