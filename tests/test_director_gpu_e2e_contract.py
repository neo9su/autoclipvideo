"""Release-gate regressions for GPU-only director composition."""
from pathlib import Path


ROOT = Path(__file__).parents[1]
DIRECTOR = (ROOT / "backend" / "director_video.py").read_text()
API = (ROOT / "backend" / "api_v2.py").read_text()
GPU = (ROOT / "gpu_service" / "main.py").read_text()


def test_control_plane_rejects_missing_subtitles_before_gpu_submission():
    assert '"Dialogue:" not in ass_content' in DIRECTOR
    assert "refusing GPU submission without timed subtitles" in DIRECTOR


def test_control_plane_rejects_empty_tts_before_gpu_submission():
    assert 'if not raw:' in DIRECTOR
    assert "refusing GPU submission with empty TTS audio" in DIRECTOR


def test_gpu_job_requires_subtitles_and_generated_audio():
    assert 'director job requires non-empty timed subtitles' in GPU
    assert 'director job requires TTS audio' in GPU
    assert 'director job TTS audio payload is missing or empty' in GPU
    assert 'must use generated TTS audio, not source-audio fallback' in GPU


def test_api_does_not_mark_success_after_local_postprocess_fallback():
    compose_body = API.split('async def _compose_video_bg', 1)[1]
    assert 'postprocess_final_video' not in compose_body
    assert 'director_status = 2' in compose_body
    assert '_get_video_duration' not in compose_body
    assert '_pad_video_to_min_duration' not in compose_body


def test_gpu_quality_gate_requires_video_and_audio_streams():
    assert 'probe.get("video_streams", 0) == 1' in GPU
    assert 'probe.get("audio_streams", 0) >= 1' in GPU
    assert '/quality' in DIRECTOR
