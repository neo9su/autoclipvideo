import ast
from pathlib import Path

from gpu_service.disk_policy import has_upload_capacity


GPU_MAIN = Path(__file__).parents[1] / "gpu_service" / "main.py"


def test_timeout_constants_are_initialized_and_referenced_consistently():
    tree = ast.parse(GPU_MAIN.read_text(encoding="utf-8"))
    assigned_names = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
        and target.id in {"_TRANSCRIBE_TIMEOUT", "_TTS_TIMEOUT"}
    }
    assert assigned_names == {"_TRANSCRIBE_TIMEOUT", "_TTS_TIMEOUT"}
    source = GPU_MAIN.read_text(encoding="utf-8")
    assert "timeout=_TRANSCRIBE_TIMEOUT" in source
    assert "timeout=_TTS_TIMEOUT" in source
    assert '_positive_timeout("TTS_TIMEOUT_SECONDS", 1800)' in source


def test_known_upload_size_is_admitted_below_legacy_fixed_floor():
    # An 86 GB volume can accept a 2 GB recording with configured headroom.
    assert has_upload_capacity(86.0, 2 * 1024**3, 20.0, 5.0)


def test_upload_policy_rejects_when_size_and_safety_floor_do_not_fit():
    assert not has_upload_capacity(6.5, 2 * 1024**3, 20.0, 5.0)
    assert not has_upload_capacity(19.9, None, 20.0, 5.0)


def test_upload_policy_rejects_invalid_thresholds():
    assert not has_upload_capacity(86.0, 1, -1.0, 5.0)
    assert not has_upload_capacity(86.0, 1, 20.0, -1.0)
