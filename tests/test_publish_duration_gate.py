import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

from publish_policy import MAX_PUBLISH_DURATION_SECONDS, validate_publish_duration
from publish_scheduler import check_video_quality


def test_publish_policy_accepts_duration_above_old_limit():
    assert MAX_PUBLISH_DURATION_SECONDS == 300.0
    assert validate_publish_duration(150.1) is None
    assert validate_publish_duration(162.8) is None
    assert validate_publish_duration(300.0) is None


def test_publish_policy_rejects_only_outside_new_bounds():
    assert "≥ 15" in validate_publish_duration(14.9)
    assert "≤ 300" in validate_publish_duration(300.1)


@pytest.mark.asyncio
async def test_quality_gate_accepts_162_8_second_1080_portrait_video(tmp_path, monkeypatch):
    probe = {
        "streams": [{"codec_type": "video", "width": 1080, "height": 1920}],
        "format": {"duration": "162.8"},
    }

    class CompletedProcess:
        returncode = 0

        async def communicate(self):
            return json.dumps(probe).encode(), b""

    async def fake_probe(*args, **kwargs):
        return CompletedProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_probe)
    passed, reason = await check_video_quality(str(tmp_path / "reclip-162-8.mp4"))
    assert passed is True
    assert reason == ""
