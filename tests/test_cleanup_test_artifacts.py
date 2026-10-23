import importlib.util,shutil
from pathlib import Path
from unittest.mock import patch
import pytest

def module(name):
    p=Path(__file__).parents[1]/'scripts'/name
    spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def fixture(tmp_path):
    m=module('cleanup_203_test_artifacts.py');root=tmp_path/'selected';root.mkdir();(root/'file.bin').write_bytes(b'recoverable'*100)
    m.ROOTS=[root];m.BASE=tmp_path/'journal';m.prepare();return m,root

def test_verified_off_host_copy_can_restore_all_files(tmp_path):
    import json
    m,root=fixture(tmp_path);archive=tmp_path/'off-host.tar';shutil.copy2(m.BASE/'artifacts.tar',archive)
    info=json.loads((m.BASE/'archive-info.json').read_text())
    with patch.object(m.shutil,'disk_usage',return_value=shutil._ntuple_diskusage(100,50,50)):
        m.finish(info['archive_sha256'],str(archive))
    assert not root.exists() and archive.exists()
    restore=module('restore_203_test_artifacts.py');restore.BASE=m.BASE;restore.restore(archive)
    assert (root/'file.bin').read_bytes()==b'recoverable'*100

def test_source_change_aborts_before_removing_any_file(tmp_path):
    import json
    m,root=fixture(tmp_path);(root/'file.bin').write_bytes(b'changed')
    info=json.loads((m.BASE/'archive-info.json').read_text())
    with pytest.raises(AssertionError,match='Source changed'):m.finish(info['archive_sha256'],'off-host')
    assert (root/'file.bin').read_bytes()==b'changed'
