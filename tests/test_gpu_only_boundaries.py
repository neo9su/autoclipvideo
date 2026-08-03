import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

from gpu_execution import RemoteGpuRequiredError
from local_media_guard import local_media_slot
from transcribe import _pad_video_to_min_duration


@pytest.mark.asyncio
async def test_local_media_slot_rejects_before_process():
    with pytest.raises(RemoteGpuRequiredError):
        async with local_media_slot("boundary test"):
            pytest.fail("local media body must never execute")


def test_duration_padding_is_fail_closed():
    with pytest.raises(RemoteGpuRequiredError):
        _pad_video_to_min_duration("result.mp4", 29.0)


def test_critical_workflows_have_local_media_boundary():
    backend = Path(__file__).parents[1] / "backend"
    for name in ("editor.py", "director_video.py", "transcribe.py", "voice_director.py", "qianchuan_quality.py"):
        source = (backend / name).read_text()
        assert "reject_local_media" in source, name


def test_smb_and_copy_tools_are_not_job_transports():
    backend = Path(__file__).parents[1] / "backend"
    forbidden = ("smb://", "cifs://", "rsync ", " scp ")
    for source_path in backend.glob("*.py"):
        source = source_path.read_text()
        assert not any(token in source for token in forbidden), source_path


def test_transfer_policy_documents_remote_node_and_storage_boundary():
    doc = (Path(__file__).parents[1] / "docs/media-storage-smb-isolation.md").read_text()
    assert "recordings/" in doc
    assert "gpu_storage/" in doc
    assert "execution_node=remote-gpu" in doc
    assert "idempotent" in doc
