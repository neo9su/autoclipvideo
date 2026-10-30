from pathlib import Path
import pytest
from scripts.relocate_media_tree import inventory,relocate,restore,linked,map_directory


def test_relocate_preserves_path_bytes_and_can_restore(tmp_path):
    source=tmp_path/'source';source.mkdir();(source/'发型.mp4').write_bytes(b'video')
    (source/'sub').mkdir();(source/'sub/audio.m4a').write_bytes(b'audio')
    destination=tmp_path/'overflow'/'archive';journal=tmp_path/'journals'/'batch.json'
    expected=inventory(source)
    relocate(source,destination,journal,reserve_bytes=0)
    assert linked(source) and inventory(source)==expected and inventory(destination)==expected
    restore(journal)
    assert not linked(source) and inventory(source)==expected and inventory(destination)==expected


def test_restore_refuses_newer_destination_content(tmp_path):
    source=tmp_path/'source';source.mkdir();(source/'clip.mp4').write_bytes(b'video')
    destination=tmp_path/'archive';journal=tmp_path/'batch.json'
    relocate(source,destination,journal,reserve_bytes=0)
    (destination/'clip.mp4').write_bytes(b'new content')
    with pytest.raises(ValueError,match='changed'):restore(journal)
    assert (source/'clip.mp4').read_bytes()==b'new content'


def test_refuses_links_and_existing_destination(tmp_path):
    source=tmp_path/'source';source.mkdir();(source/'clip').write_bytes(b'x')
    destination=tmp_path/'destination';destination.mkdir()
    with pytest.raises(ValueError):relocate(source,destination,tmp_path/'batch.json',reserve_bytes=0)
    map_directory(source/'nested',destination)
    with pytest.raises(ValueError,match='Nested links'):inventory(source)


def test_mapping_failure_restores_original(tmp_path,monkeypatch):
    import scripts.relocate_media_tree as module
    source=tmp_path/'source';source.mkdir();(source/'clip').write_bytes(b'video')
    def fail(*args):raise OSError('fixture mapping failure')
    monkeypatch.setattr(module,'map_directory',fail)
    with pytest.raises(OSError):relocate(source,tmp_path/'destination',tmp_path/'batch.json',reserve_bytes=0)
    assert not linked(source) and (source/'clip').read_bytes()==b'video'


def test_corrupted_copy_never_changes_original(tmp_path,monkeypatch):
    import scripts.relocate_media_tree as module
    source=tmp_path/'source';source.mkdir();(source/'clip').write_bytes(b'original')
    def corrupt(src,dst,**kwargs):
        dst.mkdir();(dst/'clip').write_bytes(b'corrupt')
    monkeypatch.setattr(module.shutil,'copytree',corrupt)
    with pytest.raises(ValueError,match='verification'):relocate(source,tmp_path/'destination',tmp_path/'batch.json',reserve_bytes=0)
    assert not linked(source) and (source/'clip').read_bytes()==b'original'


def test_copy_does_not_override_changed_source(tmp_path,monkeypatch):
    import scripts.relocate_media_tree as module
    source=tmp_path/'source';source.mkdir();(source/'clip').write_bytes(b'original')
    copy=module.shutil.copytree
    def change(src,dst,**kwargs):
        result=copy(src,dst,**kwargs);(src/'clip').write_bytes(b'newer');return result
    monkeypatch.setattr(module.shutil,'copytree',change)
    with pytest.raises(ValueError,match='verification'):relocate(source,tmp_path/'destination',tmp_path/'batch.json',reserve_bytes=0)
    assert not linked(source) and (source/'clip').read_bytes()==b'newer'
