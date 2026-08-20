"""Regression coverage for the GPU director delivery contract."""

import ast
from pathlib import Path


GPU_MAIN = Path(__file__).parents[1] / "gpu_service" / "main.py"


def _validation_function():
    tree = ast.parse(GPU_MAIN.read_text(encoding="utf-8"))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_validate_director_delivery_inputs"
    )
    namespace = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(GPU_MAIN), "exec"), namespace)
    return namespace[function.name]


def test_missing_subtitles_are_rejected_before_final_encode():
    validate = _validation_function()

    try:
        validate("", "encoded-voice")
    except ValueError as error:
        assert "subtitle" in str(error)
    else:
        raise AssertionError("subtitle-less jobs must be rejected")


def test_missing_voiceover_is_rejected_before_final_encode():
    validate = _validation_function()

    try:
        validate("Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,验收", "")
    except ValueError as error:
        assert "voiceover" in str(error)
    else:
        raise AssertionError("voiceover-less jobs must be rejected")


def test_quality_gate_requires_both_delivery_markers():
    source = GPU_MAIN.read_text(encoding="utf-8")

    assert '"subtitle_burned"' in source
    assert '"voiceover_mixed"' in source
    assert 'subtitle burn was not recorded' in source
    assert 'voiceover mix was not recorded' in source
