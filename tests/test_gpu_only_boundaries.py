import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

from gpu_execution import RemoteGpuRequiredError, TransferStats
from local_media_guard import local_media_slot


@pytest.mark.asyncio
async def test_legacy_local_media_slot_fails_closed():
    with pytest.raises(RemoteGpuRequiredError):
        async with local_media_slot("test media"):
            pass


def test_transfer_stats_account_bytes_and_attempts():
    stats = TransferStats("upload", "remote-gpu", input_bytes=123, output_bytes=456)
    stats.upload_attempts = 2
    stats.download_attempts = 1
    stats.temporary_files = 0
    payload = stats.as_dict()
    assert payload["execution_node"] == "remote-gpu"
    assert payload["total_bytes"] == 579
    assert payload["upload_attempts"] == 2


def test_media_modules_fail_closed_before_local_subprocess():
    for name in ("editor.py", "director_video.py", "qianchuan_quality.py", "final_video.py", "thumbnail.py"):
        source = (Path(__file__).parents[1] / "backend" / name).read_text()
        assert "reject_local_media" in source
