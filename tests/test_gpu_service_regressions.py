"""Regression coverage for GPU service startup and disk admission policy."""

import ast
from pathlib import Path

from gpu_service.disk_policy import required_free_gb

GPU_MAIN = Path(__file__).parents[1] / "gpu_service" / "main.py"


def test_timeout_constants_are_initialized():
    tree = ast.parse(GPU_MAIN.read_text(encoding="utf-8"))
    names = {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert {"_TRANSCRIBE_TIMEOUT", "_TTS_TIMEOUT"} <= names


def test_small_upload_ignores_historical_batch_floor():
    required = required_free_gb(200 * 1024**2, 10.0, 1.0)
    assert required == 10.0
    assert 86.0 >= required


def test_large_upload_keeps_size_aware_safety_margin():
    assert required_free_gb(12 * 1024**3, 10.0, 1.0) == 13.0
    assert required_free_gb(None, 10.0, 1.0) == 10.0
