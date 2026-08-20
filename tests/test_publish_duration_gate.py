import asyncio
import json
import sys

sys.path.insert(0, "backend")

from publish_scheduler import check_video_quality


def test_publish_quality_gate_accepts_162_8_seconds(monkeypatch):
    class CompletedProcess:
        returncode = 0

        async def communicate(self):
            return json.dumps({
                "streams": [{"codec_type": "video", "width": 1080, "height": 1920}],
                "format": {"duration": "162.8"},
            }).encode(), b""

    async def fake_probe(*args, **kwargs):
        return CompletedProcess()

    monkeypatch.setattr("publish_scheduler.asyncio.create_subprocess_exec", fake_probe)
    passed, reason = asyncio.run(check_video_quality("video.mp4"))
    assert passed
    assert reason == ""


def test_publish_quality_gate_rejects_duration_above_300_seconds(monkeypatch):
    class CompletedProcess:
        returncode = 0

        async def communicate(self):
            return json.dumps({
                "streams": [{"codec_type": "video", "width": 1080, "height": 1920}],
                "format": {"duration": "300.1"},
            }).encode(), b""

    async def fake_probe(*args, **kwargs):
        return CompletedProcess()

    monkeypatch.setattr("publish_scheduler.asyncio.create_subprocess_exec", fake_probe)
    passed, reason = asyncio.run(check_video_quality("video.mp4"))
    assert not passed
    assert "≤ 300 秒" in reason
