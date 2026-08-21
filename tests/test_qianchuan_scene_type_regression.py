"""Regression coverage for the GPU Qianchuan comparison-scene path."""

import ast
from pathlib import Path


ROOT = Path(__file__).parents[1]


def _director_job_function(source_path: Path) -> ast.AsyncFunctionDef:
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_do_director_job"
    )


def test_gpu_comparison_path_defines_scene_type_before_use() -> None:
    for source_path in (ROOT / "gpu_service" / "main.py", ROOT / "gpu_service_src" / "gpu_service.py"):
        function = _director_job_function(source_path)
        scene_type_assignment = next(
            node.lineno
            for node in ast.walk(function)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "scene_type" for target in node.targets)
        )
        scene_type_test_lines = [
            node.lineno
            for node in ast.walk(function)
            if isinstance(node, ast.If)
            and any(
                isinstance(name, ast.Name) and name.id == "scene_type"
                for name in ast.walk(node.test)
            )
        ]
        assert not scene_type_test_lines or scene_type_assignment < min(scene_type_test_lines)


def test_deployed_gpu_source_matches_comparison_scene_contract() -> None:
    deployed_source = (ROOT / "gpu_service" / "main.py").read_text(encoding="utf-8")
    source_tree = _director_job_function(ROOT / "gpu_service_src" / "gpu_service.py")

    assert 'scene_type = clip.get("scene_type", "")' in deployed_source
    assert any(
        isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "scene_type" for target in node.targets)
        for node in ast.walk(source_tree)
    )
