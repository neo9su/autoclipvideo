"""Regression tests for GPU service safety constants and disk policy."""

import ast
from pathlib import Path


MAIN_SOURCE = Path("gpu_service/main.py").read_text(encoding="utf-8")
MAIN_TREE = ast.parse(MAIN_SOURCE)


def _function(name: str) -> ast.FunctionDef:
    for node in ast.walk(MAIN_TREE):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"missing function: {name}")


def test_timeout_constants_are_initialized_before_use() -> None:
    assignments = {
        target.id
        for node in MAIN_TREE.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
        and target.id in {"_TRANSCRIBE_TIMEOUT", "_TTS_TIMEOUT"}
    }
    assert assignments == {"_TRANSCRIBE_TIMEOUT", "_TTS_TIMEOUT"}
    assert MAIN_SOURCE.index("_TTS_TIMEOUT =") < MAIN_SOURCE.index("timeout=_TTS_TIMEOUT")


def test_disk_policy_is_configurable_and_uses_upload_size() -> None:
    assert 'DISK_MIN_FREE_GB", "20"' in MAIN_SOURCE
    policy = _function("_upload_requires_cleanup")
    names = {node.id for node in ast.walk(policy) if isinstance(node, ast.Name)}
    assert "_disk_min_free_gb" in names
    assert "requested_bytes" in names
    reserve = _function("_disk_min_free_gb")
    reserve_names = {node.id for node in ast.walk(reserve) if isinstance(node, ast.Name)}
    assert "DISK_MIN_FREE_GB" in reserve_names


def test_healthy_86gb_volume_accepts_normal_upload() -> None:
    namespace = {"DISK_MIN_FREE_GB": 20.0}
    exec(
        compile(
            "def _disk_min_free_gb():\n"
            "    return DISK_MIN_FREE_GB\n"
            "def _upload_requires_cleanup(free_gb, requested_bytes=None):\n"
            "    requested_gb = max(0, requested_bytes or 0) / (1024 ** 3)\n"
            "    return free_gb < _disk_min_free_gb() + requested_gb\n",
            "<disk-policy>",
            "exec",
        ),
        namespace,
    )
    assert namespace["_upload_requires_cleanup"](86.0, 2 * 1024**3) is False
    assert namespace["_upload_requires_cleanup"](19.0, 1 * 1024**3) is True
