from gpu_service_src.asr_config import get_asr_config


def test_asr_config_is_explicitly_mandarin_and_domain_aware() -> None:
    config = get_asr_config()
    assert config["language"] == "zh"
    assert config["word_timestamps"] is True
    assert config["condition_on_previous_text"] is False
    assert "假发" in config["initial_prompt"]
    assert config["vad_parameters"]["speech_pad_ms"] == 300
