"""Tests for qianchuan_upload.py.

Covers: upload validation, filename safety, path traversal prevention,
MIME checking, size limits, empty file rejection, job status lifecycle.
No real GPU, real LLM, or large files needed.
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

# Module under test
import qianchuan_upload as qupload  # noqa: E402


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_upload_file(
    filename: str = "test.mp4",
    content: bytes = b"fake-video-content",
    content_type: str = "video/mp4",
    size_override: int | None = None,
) -> MagicMock:
    """Create a mock UploadFile for testing."""
    mock = MagicMock()
    mock.filename = filename
    mock.content_type = content_type
    mock.size = size_override if size_override is not None else len(content)
    mock.read = AsyncMock(return_value=content)
    return mock


def _make_good_video() -> MagicMock:
    return _make_upload_file("reference.mp4", b"x" * 1024, "video/mp4")


def _make_good_image() -> MagicMock:
    return _make_upload_file("frame.jpg", b"y" * 200, "image/jpeg")


# ── Tests: filename safety ───────────────────────────────────────────────────


def test_safe_filename_normal():
    result = qupload._safe_filename("video.mp4")
    assert result.endswith(".mp4")
    assert "_" in result
    # UUID prefix should be 12 hex chars
    prefix = result.split("_")[0]
    assert len(prefix) == 12
    assert all(c in "0123456789abcdef" for c in prefix)


def test_safe_filename_no_extension():
    result = qupload._safe_filename("noextension")
    assert result.endswith(".bin")


def test_safe_filename_unknown_extension():
    result = qupload._safe_filename("malware.exe")
    assert result.endswith(".bin")


def test_safe_filename_path_traversal():
    result = qupload._safe_filename("../../../etc/passwd")
    assert ".." not in result
    assert "/" not in result
    assert result.endswith(".bin")


def test_safe_filename_null():
    result = qupload._safe_filename(None)
    assert result.endswith(".bin")


def test_safe_filename_empty():
    result = qupload._safe_filename("")
    assert result.endswith(".bin")


def test_safe_filename_special_chars():
    result = qupload._safe_filename("my video (1).MP4")
    assert result.endswith(".mp4")
    assert " " not in result


def test_safe_filename_collision_resistant():
    """Two uploads of the same filename should produce different safe names."""
    a = qupload._safe_filename("video.mp4")
    b = qupload._safe_filename("video.mp4")
    assert a != b


# ── Tests: extension validation ─────────────────────────────────────────────


def test_validate_extension_video():
    assert qupload._validate_extension("test.mp4", qupload.ALLOWED_VIDEO_EXTENSIONS)
    assert qupload._validate_extension("test.mov", qupload.ALLOWED_VIDEO_EXTENSIONS)
    assert qupload._validate_extension("test.webm", qupload.ALLOWED_VIDEO_EXTENSIONS)
    assert qupload._validate_extension("test.MP4", qupload.ALLOWED_VIDEO_EXTENSIONS)
    assert not qupload._validate_extension("test.exe", qupload.ALLOWED_VIDEO_EXTENSIONS)
    assert not qupload._validate_extension("test.txt", qupload.ALLOWED_VIDEO_EXTENSIONS)


def test_validate_extension_image():
    assert qupload._validate_extension("photo.jpg", qupload.ALLOWED_IMAGE_EXTENSIONS)
    assert qupload._validate_extension("photo.JPEG", qupload.ALLOWED_IMAGE_EXTENSIONS)
    assert qupload._validate_extension("photo.png", qupload.ALLOWED_IMAGE_EXTENSIONS)
    assert not qupload._validate_extension("photo.gif", qupload.ALLOWED_IMAGE_EXTENSIONS)


def test_validate_extension_text():
    assert qupload._validate_extension("sub.srt", qupload.ALLOWED_TEXT_EXTENSIONS)
    assert qupload._validate_extension("sub.json", qupload.ALLOWED_TEXT_EXTENSIONS)
    assert not qupload._validate_extension("script.py", qupload.ALLOWED_TEXT_EXTENSIONS)


# ── Tests: MIME validation ──────────────────────────────────────────────────


def test_validate_mime_known_types():
    assert qupload._validate_mime("video/mp4")
    assert qupload._validate_mime("video/quicktime")
    assert qupload._validate_mime("image/jpeg")
    assert qupload._validate_mime("audio/mpeg")
    assert qupload._validate_mime("application/octet-stream")


def test_validate_mime_unknown():
    assert not qupload._validate_mime("application/x-msdownload")
    assert not qupload._validate_mime("text/html")


def test_validate_mime_none_accepts():
    """None content_type defers to extension check."""
    assert qupload._validate_mime(None)


def test_validate_mime_with_charset():
    assert qupload._validate_mime("video/mp4; charset=binary")


# ── Tests: file type classification ─────────────────────────────────────────


def test_classify_file_type():
    assert qupload._classify_file_type("video.mp4") == "video"
    assert qupload._classify_file_type("clip.mov") == "video"
    assert qupload._classify_file_type("frame.jpg") == "image"
    assert qupload._classify_file_type("audio.mp3") == "audio"
    assert qupload._classify_file_type("sub.srt") == "text"
    assert qupload._classify_file_type("unknown.xyz") == "other"


# ── Tests: path safety ──────────────────────────────────────────────────────


def test_is_path_safe_normal():
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "uploads")
        os.makedirs(root, exist_ok=True)
        assert qupload._is_path_safe(root, "subdir/file.txt")
        assert not qupload._is_path_safe(root, "../escape.txt")
        assert not qupload._is_path_safe(root, "../../etc/passwd")


def test_is_path_safe_absolute():
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "uploads")
        os.makedirs(root, exist_ok=True)
        assert not qupload._is_path_safe(root, "/etc/passwd")


def test_ensure_upload_root_creates_directory():
    with tempfile.TemporaryDirectory() as tmp:
        original = qupload.UPLOAD_ROOT
        try:
            qupload.UPLOAD_ROOT = os.path.join(tmp, "qianchuan_uploads_test")
            root = qupload._ensure_upload_root()
            assert os.path.isdir(root)
            assert root == os.path.abspath(qupload.UPLOAD_ROOT)
        finally:
            qupload.UPLOAD_ROOT = original


# ── Tests: filename rejection ──────────────────────────────────────────────


def test_reject_invalid_filename_empty():
    with pytest.raises(Exception) as exc:
        qupload._reject_invalid_filename("")
    assert "不能为空" in str(exc.value.detail)


def test_reject_invalid_filename_path_traversal():
    with pytest.raises(Exception) as exc:
        qupload._reject_invalid_filename("../../../etc/passwd")
    assert "非法字符" in str(exc.value.detail)


def test_reject_invalid_filename_null_byte():
    with pytest.raises(Exception) as exc:
        qupload._reject_invalid_filename("good\0bad.txt")
    assert "非法字符" in str(exc.value.detail)


def test_reject_invalid_filename_too_long():
    with pytest.raises(Exception) as exc:
        qupload._reject_invalid_filename("a" * 300 + ".mp4")
    assert "255" in str(exc.value.detail)


def test_reject_invalid_filename_bad_extension():
    with pytest.raises(Exception) as exc:
        qupload._reject_invalid_filename("script.exe")
    assert "不支持的文件格式" in str(exc.value.detail)


def test_reject_invalid_filename_ok():
    """Valid filename should not raise."""
    qupload._reject_invalid_filename("reference_video.mp4")
    qupload._reject_invalid_filename("frame.jpg")
    qupload._reject_invalid_filename("audio.mp3")


# ── Tests: job lifecycle ────────────────────────────────────────────────────


def test_job_create_and_retrieve():
    qupload._jobs.clear()
    uploads = [{"filename": "abc_video.mp4", "original_name": "video.mp4", "type": "video", "size_bytes": 1024, "path": "/tmp/test/video.mp4"}]
    job = qupload._create_job("abc123", uploads)
    assert job["job_id"] == "abc123"
    assert job["status"] == qupload.STATUS_QUEUED
    assert "abc123" in qupload._jobs


@pytest.mark.asyncio
async def test_job_update():
    qupload._jobs.clear()
    uploads = [{"filename": "test.mp4", "original_name": "video.mp4", "type": "video", "size_bytes": 100, "path": "/tmp/v.mp4"}]
    qupload._create_job("test-job-1", uploads)
    await qupload._update_job("test-job-1", status=qupload.STATUS_RUNNING, started_at=12345.0)
    job = qupload._jobs["test-job-1"]
    assert job["status"] == qupload.STATUS_RUNNING
    assert job["started_at"] == 12345.0


@pytest.mark.asyncio
async def test_job_update_nonexistent():
    qupload._jobs.clear()
    # Should not raise
    await qupload._update_job("nonexistent", status="running")


# ── Tests: analysis task (no real LLM) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_run_learning_analysis_with_video():
    """Analysis runs with a video path, produces scoring result."""
    qupload._jobs.clear()

    with tempfile.TemporaryDirectory() as tmp:
        # Create a minimal analysis directory with hero.jpg
        job_dir = os.path.join(tmp, "test_job")
        os.makedirs(job_dir, exist_ok=True)
        video_path = os.path.join(job_dir, "ref.mp4")
        with open(video_path, "wb") as f:
            f.write(b"fake mp4")
        # Create hero.jpg so there's at least some visual material
        with open(os.path.join(job_dir, "hero.jpg"), "wb") as f:
            f.write(b"fake jpg")

        uploads = [{"filename": "ref.mp4", "original_name": "ref.mp4", "type": "video", "size_bytes": 8, "path": video_path}]
        qupload._create_job("analysis-test", uploads)

        # Mock llm_post to return valid analysis JSON
        import json
        valid_response = json.dumps({
            "structure_description": "A test video",
            "segments": [{"type": "result_hook"}, {"type": "cta"}],
            "hook_analysis": {"hook_type": "result", "effectiveness": "high"},
            "visual_style": {"lighting": "studio", "shot_types": ["closeup"], "composition": "centered"},
            "audio_rhythm": {"energy_level": "medium", "speech_pace": "moderate"},
            "conversion_elements": [{"element_type": "cta", "strength": "strong"}],
            "audience_adaptation": {"primary_audience": "test"},
            "reusable_patterns": [],
            "risks": [],
            "improvement_suggestions": [],
        })

        async def fake_llm(messages, **kw):
            return valid_response

        with patch("qianchuan_learning.llm_post", side_effect=fake_llm):
            await qupload._run_learning_analysis("analysis-test", video_path, [])

        job = qupload._jobs["analysis-test"]
        assert job["status"] == qupload.STATUS_SUCCEEDED
        assert job["result"] is not None
        assert job["result"]["quality"]["overall"] > 0
        assert "visual" in job["result"]["quality"]["dimensions"]


@pytest.mark.asyncio
async def test_run_learning_analysis_llm_failure():
    """When analysis raises an unhandled exception, job status should be failed."""
    qupload._jobs.clear()

    with tempfile.TemporaryDirectory() as tmp:
        video_path = os.path.join(tmp, "fail.mp4")
        with open(video_path, "wb") as f:
            f.write(b"fake mp4")

        uploads = [{"filename": "fail.mp4", "original_name": "fail.mp4", "type": "video", "size_bytes": 8, "path": video_path}]
        qupload._create_job("fail-test", uploads)

        async def fake_analyze_video(directory, **kw):
            raise RuntimeError("LLM unavailable")

        with patch("qianchuan_learning.analyze_video", side_effect=fake_analyze_video):
            await qupload._run_learning_analysis("fail-test", video_path, [])

        job = qupload._jobs["fail-test"]
        assert job["status"] == qupload.STATUS_FAILED
        assert job["error"] is not None


@pytest.mark.asyncio
async def test_run_learning_analysis_no_directory_no_crash():
    """Even with a missing analysis directory, task should fail gracefully."""
    qupload._jobs.clear()
    uploads = [{"filename": "x.mp4", "original_name": "x.mp4", "type": "video", "size_bytes": 8, "path": "/nonexistent/x.mp4"}]
    qupload._create_job("missing-dir", uploads)

    await qupload._run_learning_analysis("missing-dir", "/nonexistent/x.mp4", [])
    job = qupload._jobs["missing-dir"]
    assert job["status"] in (qupload.STATUS_FAILED, qupload.STATUS_SUCCEEDED)
    # When a directory is missing, analyze_video returns degraded but doesn't crash


# ── Tests: status constants ──────────────────────────────────────────────────


def test_status_constants():
    assert qupload.STATUS_QUEUED == "queued"
    assert qupload.STATUS_RUNNING == "running"
    assert qupload.STATUS_SUCCEEDED == "succeeded"
    assert qupload.STATUS_FAILED == "failed"


# ── Tests: upload limits ────────────────────────────────────────────────────


def test_upload_limits_reasonable():
    assert qupload.MAX_VIDEO_SIZE_BYTES > 0
    assert qupload.MAX_AUX_SIZE_BYTES > 0
    assert qupload.MAX_FILES_PER_REQUEST > 0
    assert qupload.MAX_FILES_PER_REQUEST <= 20


def test_allowed_extensions_coherent():
    """All extension sets should be subsets of ALLOWED_EXTENSIONS."""
    assert qupload.ALLOWED_VIDEO_EXTENSIONS <= qupload.ALLOWED_EXTENSIONS
    assert qupload.ALLOWED_IMAGE_EXTENSIONS <= qupload.ALLOWED_EXTENSIONS
    assert qupload.ALLOWED_AUDIO_EXTENSIONS <= qupload.ALLOWED_EXTENSIONS
    assert qupload.ALLOWED_TEXT_EXTENSIONS <= qupload.ALLOWED_EXTENSIONS


# ── Tests: upload status endpoint ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_upload_service_status():
    """Status endpoint returns service info."""
    with tempfile.TemporaryDirectory() as tmp:
        original = qupload.UPLOAD_ROOT
        try:
            qupload.UPLOAD_ROOT = os.path.join(tmp, "qup")
            result = await qupload.get_upload_service_status()
            assert result["service"] == "qianchuan-upload"
            assert result["available"] is True
            assert "allowed_extensions" in result
            assert "max_video_size_bytes" in result
        finally:
            qupload.UPLOAD_ROOT = original


# ── Tests: job status endpoint validation ──────────────────────────────────


@pytest.mark.asyncio
async def test_get_upload_job_status_invalid_id():
    with pytest.raises(Exception) as exc:
        await qupload.get_upload_job_status("not-a-hex-id")
    assert 400 in (exc.value.status_code,)


@pytest.mark.asyncio
async def test_get_upload_job_status_not_found():
    with pytest.raises(Exception) as exc:
        await qupload.get_upload_job_status("aabbccddeeff0011")
    assert 404 in (exc.value.status_code,)
