from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GPU_SOURCE = (ROOT / "gpu_service" / "main.py").read_text(encoding="utf-8")
DIRECTOR_SOURCE = (ROOT / "backend" / "director_video.py").read_text(encoding="utf-8")


def test_gpu_director_rejects_missing_subtitles_and_tts_before_queueing():
    assert 'if "Dialogue:" not in (req.ass_content or "")' in GPU_SOURCE
    assert 'if not req.tts_audio_b64:' in GPU_SOURCE


def test_gpu_director_cannot_complete_without_burned_subtitles_or_mixed_tts():
    assert 'if "Dialogue:" not in (ass_content or ""):' in GPU_SOURCE
    assert 'if not has_tts:' in GPU_SOURCE
    assert '"subtitles_burned": has_subs' in GPU_SOURCE
    assert '"tts_audio_mixed": has_tts' in GPU_SOURCE
    assert 'if not job.get("subtitles_burned"):' in GPU_SOURCE
    assert 'if not job.get("tts_audio_mixed"):' in GPU_SOURCE


def test_control_plane_requires_remote_quality_gate_before_returning_output():
    assert 'if "Dialogue:" not in ass_content:' in DIRECTOR_SOURCE
    assert 'if not tts_b64:' in DIRECTOR_SOURCE
    assert 'if not data.get("subtitles_burned") or not data.get("tts_audio_mixed"):' in DIRECTOR_SOURCE
    assert 'director-jobs/{job_id}/quality' in DIRECTOR_SOURCE
    assert 'if quality_response.status != 200 or not quality.get("ok"):' in DIRECTOR_SOURCE
