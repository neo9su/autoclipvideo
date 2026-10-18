import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location("clip_patch", Path(__file__).parents[1] / "scripts/patch_clip_low_disk.py")
patch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patch)


class HTTPException(Exception):
    def __init__(self, status_code, detail):
        self.status_code, self.detail = status_code, detail


SOURCE = '''async def create_clip_job(req):
    free_gb = req.free_gb
''' + patch.OLD + '''
            status_code=507,
            detail=f"Insufficient disk space: {free_gb:.1f}GB free"
        )
    if not req.segments:
        raise HTTPException(status_code=422, detail="segments list is empty")
    job_id = "new-job"
    _clip_jobs[job_id] = {"status": "queued"}
    return job_id
'''


def run(source, free=1, segments=(1,)):
    jobs = {"existing": {"status": "processing"}}
    env = dict(CLIP_MIN_FREE_GB=20, _clip_jobs=jobs, HTTPException=HTTPException,
               logger=SimpleNamespace(warning=lambda *args: None))
    exec(source, env)
    return asyncio.run(env["create_clip_job"](SimpleNamespace(free_gb=free, segments=segments))), jobs


def test_original_reproduces_unbound_job_id():
    with pytest.raises(UnboundLocalError):
        run(SOURCE)


def test_low_space_returns_507_instead():
    with pytest.raises(HTTPException) as error:
        run(patch.patch_source(SOURCE))
    assert error.value.status_code == 507


def test_adequate_space_preserves_existing_job():
    result, jobs = run(patch.patch_source(SOURCE), free=20)
    assert result == "new-job"
    assert jobs["existing"] == {"status": "processing"}


def test_empty_segments_still_rejected():
    with pytest.raises(HTTPException) as error:
        run(patch.patch_source(SOURCE), free=30, segments=())
    assert error.value.status_code == 422


def test_source_drift_refused():
    with pytest.raises(RuntimeError):
        patch.patch_source(SOURCE.replace("CLIP_MIN_FREE_GB", "OTHER_LIMIT"))


def test_windows_line_endings_preserved():
    result = patch.patch_source(SOURCE.replace("\n", "\r\n"))
    assert "\r\n" in result
    assert "\n" not in result.replace("\r\n", "")
    with pytest.raises(HTTPException) as error:
        run(result)
    assert error.value.status_code == 507
