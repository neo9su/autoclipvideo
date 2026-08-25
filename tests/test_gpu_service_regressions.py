from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))
from gpu_service.disk_policy import has_upload_capacity


def test_timeout_constants_are_initialized_before_use():
    source = Path("gpu_service/main.py").read_text(encoding="utf-8")
    transcribe_definition = source.index("_TRANSCRIBE_TIMEOUT =")
    tts_definition = source.index("_TTS_TIMEOUT =")
    assert "TRANSCRIBE_TIMEOUT_SECONDS" in source[transcribe_definition:]
    assert "TTS_TIMEOUT_SECONDS" in source[tts_definition:]
    assert source.index("_positive_timeout") < transcribe_definition
    assert source.index("_positive_timeout") < tts_definition


def test_healthy_volume_is_not_rejected_by_legacy_capacity_threshold():
    assert has_upload_capacity(86.0, 500 * 1024 * 1024, 20.0, 5.0)


def test_low_disk_upload_is_rejected_with_reserve():
    assert not has_upload_capacity(2.0, 2 * 1024**3, 10.0, 1.0)


def test_unknown_upload_size_uses_minimum_free_reserve():
    assert has_upload_capacity(10.1, None, 10.0, 1.0)


def test_clip_admission_does_not_use_legacy_batch_quota():
    source = Path("gpu_service/main.py").read_text(encoding="utf-8")
    assert "BATCH_UPLOAD_LIMIT_GB" not in source


def test_tts_failure_logging_does_not_reference_caller_only_scene_type():
    source = Path("backend/voice_director.py").read_text(encoding="utf-8")
    assert "GPU TTS exception for scene_type={scene_type}" not in source
    assert "GPU TTS exception for room_id=%s emotion=%s" in source


def test_upload_streaming_keeps_transport_chunks_out_of_logical_job_model():
    source = Path("backend/sync.py").read_text()
    assert "AsyncIterablePayload" in source
    assert "read_source_chunks" in source
    assert "sync_file" in source
