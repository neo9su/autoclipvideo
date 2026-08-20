"""Release gates for the GPU-only director subtitle/voiceover contract."""

from pathlib import Path


GPU_SERVICE = Path(__file__).parents[1] / "gpu_service" / "main.py"
GPU_SERVICE_SOURCE = Path(__file__).parents[1] / "gpu_service_src" / "gpu_service.py"
API = Path(__file__).parents[1] / "backend" / "api_v2.py"


def test_gpu_final_encode_requires_burned_subtitles():
    source = GPU_SERVICE.read_text(encoding="utf-8")

    assert "non-empty timed subtitles are required" in source
    assert 'r"(?m)^Dialogue:' in source
    assert "ass=filename=" in source


def test_gpu_final_encode_requires_generated_voiceover_and_never_source_fallback():
    source = GPU_SERVICE.read_text(encoding="utf-8")

    assert "generated voiceover is required" in source
    assert "generated voiceover audio is missing" in source
    assert "[1:a]acompressor" in source
    assert "elif merged_has_audio" not in source


def test_api_only_marks_completed_after_composer_and_remote_duration_gate():
    source = API.read_text(encoding="utf-8")
    compose = source.index("output_path = await composer.compose_final_video")
    status = source.index("director_status = 2", compose)

    assert source.index("quality_report", compose) < status
    assert source.index("director_final_video = ?", compose) < status


def test_gpu_quality_probe_decodes_video_and_audio_payloads():
    source = GPU_SERVICE.read_text(encoding="utf-8")

    assert '"video_decode"' in source
    assert '"audio_decode"' in source
    assert '"-frames:v", "1"' in source
    assert '"-map", "0:a:0"' in source


def test_deployment_source_exposes_the_same_quality_contract():
    source = GPU_SERVICE_SOURCE.read_text(encoding="utf-8")

    assert '@app.get("/director-jobs/{job_id}/quality")' in source
    assert '"video_decode"' in source
    assert '"audio_decode"' in source
    assert '"execution_node": "remote-gpu"' in source
    assert '"subtitle_burned"' in source
    assert '"generated_voiceover_mixed"' in source
