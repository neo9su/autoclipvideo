import importlib.util
from pathlib import Path
from unittest.mock import patch
import json

import pytest

spec = importlib.util.spec_from_file_location(
    'migration_worker', Path(__file__).parents[1] / 'scripts/migrate_c_media_to_222.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


def test_checkpoint_retries_windows_reader_lock(tmp_path):
    replace = worker.os.replace
    attempts = []

    def busy_twice(source, target):
        attempts.append(1)
        if len(attempts) < 3:
            raise PermissionError('Windows reader denies replacement')
        replace(source, target)

    with patch.object(worker, 'AUDIT', tmp_path), patch.object(worker.os, 'replace', busy_twice), patch.object(worker.time, 'sleep'):
        worker.save({'migrated_files': 312})
    assert len(attempts) == 3
    assert json.loads((tmp_path / 'status.json').read_text())['migrated_files'] == 312


def test_permanent_checkpoint_failure_preserves_last_good_status(tmp_path):
    previous = tmp_path / 'status.json'
    previous.write_text('{"migrated_files":311}')
    with patch.object(worker, 'AUDIT', tmp_path), patch.object(worker.os, 'replace', side_effect=PermissionError('still locked')), patch.object(worker.time, 'sleep'):
        with pytest.raises(PermissionError):
            worker.save({'migrated_files': 312})
    assert json.loads(previous.read_text())['migrated_files'] == 311
    assert json.loads((tmp_path / 'status.writing').read_text())['migrated_files'] == 312
