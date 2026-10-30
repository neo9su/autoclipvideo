import importlib.util
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('cache_migration',Path(__file__).parents[1]/'scripts/migrate_completed_aid_cache.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def test_migrate_link_resume_restore_preserve_media(tmp_path,monkeypatch):
    root=tmp_path/'spool';dest=tmp_path/'disk2';root.mkdir()
    monkeypatch.setattr(m,'ROOT',root);monkeypatch.setattr(m,'DEST',dest)
    source=root/'job-1-artifacts';source.mkdir();(source/'recording.mp4').write_bytes(b'original recording replica')
    jobs=[{'id':1,'status':'SUCCEEDED','node':'gpu-222'}]
    m.migrate(jobs);assert source.is_symlink()
    assert (source/'recording.mp4').read_bytes()==b'original recording replica'
    state=m.migrate(jobs);assert len(state['items'])==1
    m.restore();assert source.is_dir() and not source.is_symlink()
    assert (source/'recording.mp4').read_bytes()==(dest/'job-1-artifacts'/'recording.mp4').read_bytes()


def test_nonterminal_and_checksum_failure_leave_source_intact(tmp_path,monkeypatch):
    root=tmp_path/'spool';root.mkdir();dest=tmp_path/'disk2'
    monkeypatch.setattr(m,'ROOT',root);monkeypatch.setattr(m,'DEST',dest)
    source=root/'job-1-artifacts';source.mkdir();(source/'recording.mp4').write_bytes(b'source preserved')
    with pytest.raises(AssertionError):m.migrate([{'id':1,'status':'RUNNING','node':'gpu-222'}])
    real=m.digest
    monkeypatch.setattr(m,'digest',lambda path: 'bad' if dest in path.parents else real(path))
    with pytest.raises(AssertionError):m.migrate([{'id':1,'status':'SUCCEEDED','node':'gpu-222'}])
    assert not source.is_symlink() and (source/'recording.mp4').read_bytes()==b'source preserved'
