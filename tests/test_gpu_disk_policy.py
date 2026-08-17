from gpu_service.disk_policy import has_upload_capacity


def test_timeout_constants_are_defined_in_gpu_service_source():
    source = open("gpu_service/main.py", encoding="utf-8").read()
    assert "_TRANSCRIBE_TIMEOUT = _positive_timeout" in source
    assert "_TTS_TIMEOUT = _positive_timeout" in source


def test_current_healthy_volume_accepts_normal_transcription_upload():
    assert has_upload_capacity(86.0, 2 * 1024**3, 20.0, 5.0)


def test_upload_policy_accounts_for_file_size_and_reserve():
    assert has_upload_capacity(27.0, 20 * 1024**3, 10.0, 2.0)
    assert not has_upload_capacity(21.9, 20 * 1024**3, 10.0, 2.0)


def test_upload_policy_rejects_below_minimum_after_cleanup():
    assert not has_upload_capacity(9.9, 1 * 1024**3, 10.0, 2.0)
