import io
import json
import pytest
from scripts.archive_clip_temps import digest,send,receive,reclaim,restore,fingerprint


def fixture(tmp_path):
    root=tmp_path/'source';base=root/('a'*16);base.mkdir(parents=True)
    p=base/'seg0.mp4';p.write_bytes(b'video bytes')
    (base/'final.mp4').write_bytes(b'final untouched')
    plan={'job_id':'a'*16,'files':[{'name':p.name,'bytes':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns,'sha256':digest(p)}]}
    return root,plan


def test_archive_verify_reclaim_and_restore(tmp_path):
    root,plan=fixture(tmp_path);stream=io.BytesIO();send(root,plan,stream);stream.seek(0)
    archive=tmp_path/'archive';receipt=receive(archive,stream);reclaim(root,plan,receipt)
    assert not (root/plan['job_id']/'seg0.mp4').exists()
    assert (root/plan['job_id']/'final.mp4').read_bytes()==b'final untouched'
    assert restore(root,archive/plan['job_id'])==1
    assert (root/plan['job_id']/'seg0.mp4').read_bytes()==b'video bytes'


def test_truncated_archive_retains_source(tmp_path):
    root,plan=fixture(tmp_path);stream=io.BytesIO();send(root,plan,stream)
    with pytest.raises(ValueError):receive(tmp_path/'archive',io.BytesIO(stream.getvalue()[:-1]))
    assert (root/plan['job_id']/'seg0.mp4').exists()


def test_refuse_non_temp_name(tmp_path):
    root,plan=fixture(tmp_path);plan['files'][0]['name']='original.mp4'
    with pytest.raises(ValueError):send(root,plan,io.BytesIO())


def test_receipt_and_source_drift_block_reclaim(tmp_path):
    root,plan=fixture(tmp_path)
    with pytest.raises(ValueError):reclaim(root,plan,{})
    (root/plan['job_id']/'seg0.mp4').write_bytes(b'new')
    with pytest.raises(ValueError):reclaim(root,plan,{'fingerprint':fingerprint(plan)})
