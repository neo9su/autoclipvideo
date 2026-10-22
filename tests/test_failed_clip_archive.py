import importlib.util,hashlib,json,shutil
from pathlib import Path
from unittest.mock import patch
import pytest

def fixture(tmp_path):
    spec=importlib.util.spec_from_file_location('archive',Path(__file__).parents[1]/'scripts/archive_unreferenced_failed_clips.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    m.BASE=tmp_path/'journal';m.BASE.mkdir();m.ROOT=tmp_path/'clips';p=m.ROOT/'0123456789abcdef';p.mkdir(parents=True);(p/'seg0.mp4').write_bytes(b'video-data'*100)
    (m.BASE/'batches.json').write_text(json.dumps([[str(p)]]));m.validate_dirs=lambda dirs:None
    return m,p

def test_streamed_archive_hash_matches_and_verified_removal(tmp_path):
    m,p=fixture(tmp_path)
    with patch.object(m.shutil,'disk_usage',return_value=shutil._ntuple_diskusage(20*2**30,1,10*2**30)):
        m.prepare(0)
        archive=m.BASE/'batch-000'/'clips.tar';info=json.loads((archive.parent/'archive-info.json').read_text());assert hashlib.sha256(archive.read_bytes()).hexdigest()==info['archive_sha256']
        off=tmp_path/'offhost.tar';shutil.copy2(archive,off)
        m.finish(0,info['archive_sha256'],str(off))
    assert not p.exists() and off.exists()

def test_changed_source_aborts_before_removal(tmp_path):
    m,p=fixture(tmp_path)
    with patch.object(m.shutil,'disk_usage',return_value=shutil._ntuple_diskusage(20*2**30,1,10*2**30)):m.prepare(0)
    info=json.loads((m.BASE/'batch-000'/'archive-info.json').read_text());(p/'seg0.mp4').write_bytes(b'new')
    with pytest.raises(AssertionError,match='Source changed'):m.finish(0,info['archive_sha256'],'offhost')
    assert (p/'seg0.mp4').exists()
