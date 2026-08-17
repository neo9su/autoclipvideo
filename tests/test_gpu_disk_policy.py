from gpu_service.disk_policy import can_accept_upload, required_free_gb


def test_timeout_constants_are_defined_in_gpu_service_source():
    source = open("gpu_service/main.py", encoding="utf-8").read()
    assert "_TRANSCRIBE_TIMEOUT = int(" in source
    assert "_TTS_TIMEOUT = int(" in source


def test_current_healthy_volume_accepts_normal_transcription_upload():
    assert can_accept_upload(86.0, 2 * 1024**3, 10.0, 2.0)


def test_upload_policy_accounts_for_file_size_and_reserve():
    required = required_free_gb(20 * 1024**3, 10.0, 2.0)
    assert required == 22.0
    assert not can_accept_upload(21.9, 20 * 1024**3, 10.0, 2.0)


def test_upload_policy_rejects_below_minimum_after_cleanup():
    assert not can_accept_upload(9.9, 1 * 1024**3, 10.0, 2.0)
