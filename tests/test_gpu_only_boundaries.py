from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

import gpu_execution
from gpu_execution import RemoteGpuRequiredError, media_fingerprint
from local_media_guard import local_media_slot
from final_video import postprocess_final_video
from qianchuan_quality import check_qianchuan_video_quality


@pytest.mark.asyncio
async def test_local_media_slot_rejects_execution():
    with pytest.raises(RemoteGpuRequiredError):
        async with local_media_slot("test"):
            pass


@pytest.mark.asyncio
async def test_final_postprocess_never_invokes_local_ffmpeg():
    with pytest.raises(RemoteGpuRequiredError):
        await postprocess_final_video("input.mp4")


@pytest.mark.asyncio
async def test_quality_check_requires_remote_service(monkeypatch):
    monkeypatch.setattr(gpu_execution, "GPU_SERVICE_URL", "http://127.0.0.1:8877")
    with pytest.raises(RemoteGpuRequiredError):
        await check_qianchuan_video_quality("output.mp4")


def test_media_fingerprint_is_stable(tmp_path):
    source = tmp_path / "input.mp4"
    source.write_bytes(b"test-media")
    assert media_fingerprint(str(source)) == media_fingerprint(str(source))
