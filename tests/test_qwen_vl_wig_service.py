import ast
from pathlib import Path


def _load_alignment_function():
    source = Path("services/qwen_vl_wig_service.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_align_observations")
    module = ast.Module(body=[function], type_ignores=[])
    namespace = {}
    exec(compile(module, "qwen_vl_wig_service.py", "exec"), namespace)
    return namespace["_align_observations"]


def test_aligns_model_sequence_indices_to_requested_windows():
    align = _load_alignment_function()
    metadata = [
        {"window_index": 0, "time_sec": 10},
        {"window_index": 0, "time_sec": 15},
        {"window_index": 1, "time_sec": 30},
    ]
    observations = [
        {"window_index": 0, "time_sec": 10, "wear_state": "stable_wearing"},
        {"window_index": 1, "time_sec": 15, "wear_state": "stable_wearing"},
        {"window_index": 2, "time_sec": 30, "wear_state": "transition"},
    ]
    assert [item["window_index"] for item in align(observations, metadata)] == [0, 0, 1]


def test_drops_hallucinated_or_missing_timestamps():
    align = _load_alignment_function()
    metadata = [{"window_index": 0, "time_sec": 10}]
    observations = [{"time_sec": 11}, {"wear_state": "stable_wearing"}]
    assert align(observations, metadata) == []
