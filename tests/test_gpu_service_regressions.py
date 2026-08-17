"""Regression coverage for GPU timeout and disk admission configuration."""

import ast
from pathlib import Path


from gpu_service.disk_policy import configured_positive_int, required_free_gb


MAIN_SOURCE = Path("gpu_service/main.py").read_text(encoding="utf-8")


def test_timeout_constants_are_initialized_before_use() -> None:
    tree = ast.parse(MAIN_SOURCE)
    assignments = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
        and target.id in {"_TRANSCRIBE_TIMEOUT", "_TTS_TIMEOUT"}
    }
    assert assignments == {"_TRANSCRIBE_TIMEOUT", "_TTS_TIMEOUT"}
    assert "timeout=_TRANSCRIBE_TIMEOUT" in MAIN_SOURCE
    assert "timeout=_TTS_TIMEOUT" in MAIN_SOURCE


def test_timeout_settings_fall_back_for_invalid_values() -> None:
    environment = {
        "TRANSCRIBE_TIMEOUT_SECONDS": "not-a-number",
        "TTS_TIMEOUT_SECONDS": "0",
    }
    assert configured_positive_int(environment, "TRANSCRIBE_TIMEOUT_SECONDS", 3600) == 3600
    assert configured_positive_int(environment, "TTS_TIMEOUT_SECONDS", 1800) == 1800


def test_disk_policy_is_size_aware() -> None:
    assert required_free_gb(200 * 1024**2, 20.0, 1.0) == 20.0
    assert required_free_gb(12 * 1024**3, 20.0, 1.0) == 20.0
    assert required_free_gb(25 * 1024**3, 20.0, 1.0) == 26.0
    assert 86.0 >= required_free_gb(2 * 1024**3, 20.0, 1.0)
