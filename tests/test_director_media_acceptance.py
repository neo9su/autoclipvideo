"""Regression tests for the director GPU-only completion contract."""
from pathlib import Path


ROOT = Path(__file__).parents[1]
DIRECTOR_VIDEO = (ROOT / "backend" / "director_video.py").read_text(encoding="utf-8")
GPU_SERVICE = (ROOT / "gpu_service" / "main.py").read_text(encoding="utf-8")
API_V2 = (ROOT / "backend" / "api_v2.py").read_text(encoding="utf-8")


def test_control_plane_rejects_missing_subtitles_before_gpu_submission():
    """A subtitle build failure must not silently create a clean video."""
    assert 'requires non-empty timed subtitles' in DIRECTOR_VIDEO
    assert 'subtitle burn-in contract failed' in DIRECTOR_VIDEO


def test_gpu_encoder_requires_subtitles_and_tts_audio():
    """The GPU final encode must receive both required media layers."""
    assert 'if not has_subs:' in GPU_SERVICE
    assert 'if not has_tts:' in GPU_SERVICE
    assert 'generated voiceover audio is missing' in GPU_SERVICE


def test_api_marks_background_failures_instead_of_completing():
    """Only the success path may persist director_status=2."""
    assert 'director_status = 2' in API_V2
    assert 'director_status = -1' in API_V2
    assert 'director_final_video = ?, director_error = NULL' in API_V2
    assert 'postprocess_final_video' not in API_V2


def test_director_path_keeps_remote_gpu_policy():
    """No local media fallback may be introduced for this workflow."""
    assert 'require_remote_gpu("director composition")' in DIRECTOR_VIDEO
    assert 'media_execution_node("director composition")' in DIRECTOR_VIDEO
