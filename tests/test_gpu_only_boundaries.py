"""GPU-only boundary tests for issue #28."""
import asyncio
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def test_local_media_slot_is_disabled():
    from local_media_guard import LocalMediaDisabledError, local_media_slot

    async def exercise():
        with pytest.raises(LocalMediaDisabledError):
            async with local_media_slot("test"):
                pass

    asyncio.run(exercise())


def test_remote_gpu_rejects_loopback(monkeypatch):
    monkeypatch.setenv("GPU_SERVICE_URL", "http://127.0.0.1:8877")
    module = importlib.import_module("gpu_execution")
    module = importlib.reload(module)
    with pytest.raises(module.RemoteGpuRequiredError):
        module.require_remote_gpu("test")


def test_storage_policy_marks_shared_paths():
    from gpu_execution import media_storage_policy

    policy = media_storage_policy("/Volumes/SMB-recordings", "/srv/gpu_storage")
    assert policy["recordings_isolated"] is False
    assert policy["gpu_storage_isolated"] is True


def test_source_has_no_reachable_local_clip_fallback():
    source = (BACKEND / "editor.py").read_text()
    generate_body = source[source.index("async def edit_recording("):source.index("async def edit_recording_multi(")]
    assert "_fast_local_clip(" not in generate_body
    assert "local execution is forbidden" in generate_body
