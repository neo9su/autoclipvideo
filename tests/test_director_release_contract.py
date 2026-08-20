"""Fail-closed release contracts for GPU director composition."""

from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_control_plane_rejects_empty_subtitle_render():
    source = (ROOT / "backend" / "director_video.py").read_text(encoding="utf-8")
    assert '"Dialogue:" not in ass_content' in source
    assert "refusing an uncaptioned final video" in source


def test_gpu_director_requires_generated_voiceover_and_subtitles():
    source = (ROOT / "gpu_service" / "main.py").read_text(encoding="utf-8")
    assert '"Dialogue:" not in ass_content' in source
    assert "not tts_audio_b64" in source
    assert "final director video has no audio stream" in source


def test_gpu_only_director_path_has_no_source_audio_fallback():
    source = (ROOT / "gpu_service" / "main.py").read_text(encoding="utf-8")
    director_start = source.index("async def _do_director_job(")
    director_end = source.index("async def _run_director_job(", director_start)
    director_source = source[director_start:director_end]
    assert "elif merged_has_audio" not in director_source

