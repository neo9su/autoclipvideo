import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

from gpu_execution import RemoteGpuRequiredError
from local_media_guard import local_media_slot


@pytest.mark.asyncio
async def test_local_media_slot_rejects_before_process():
    with pytest.raises(RemoteGpuRequiredError):
        async with local_media_slot("boundary test"):
            pytest.fail("local media body must never execute")
