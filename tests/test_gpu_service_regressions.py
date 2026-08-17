from pathlib import Path

from gpu_service.disk_policy import upload_rejection_reason


def test_timeout_constants_are_initialized_before_use():
    source = Path("gpu_service/main.py").read_text(encoding="utf-8")
    transcribe_definition = source.index("_TRANSCRIBE_TIMEOUT =")
    tts_definition = source.index("_TTS_TIMEOUT =")
    assert "_TRANSCRIBE_TIMEOUT" in source[transcribe_definition:]
    assert "_TTS_TIMEOUT" in source[tts_definition:]
    assert "TRANSCRIBE_TIMEOUT_SECONDS" in source[transcribe_definition:]
    assert "TTS_TIMEOUT_SECONDS" in source[tts_definition:]


def test_healthy_volume_is_not_rejected_by_legacy_capacity_threshold():
    assert upload_rejection_reason(
        86.0,
        500 * 1024 * 1024,
        minimum_free_gb=10.0,
        upload_reserve_gb=1.0,
    ) is None


def test_low_disk_upload_is_rejected_with_reserve():
    reason = upload_rejection_reason(
        2.0,
        2 * 1024 * 1024 * 1024,
        minimum_free_gb=10.0,
        upload_reserve_gb=1.0,
    )
    assert reason and "reserve" in reason


def test_unknown_upload_size_uses_minimum_free_reserve():
    assert upload_rejection_reason(
        10.1, None, minimum_free_gb=10.0, upload_reserve_gb=1.0
    ) is None
