"""Exercise the actual payload expression without loading media dependencies."""
import ast
from pathlib import Path

import pytest


SOURCE = Path(__file__).parents[1] / "backend" / "director_video.py"


@pytest.mark.parametrize("config, expected", [
    ({}, {}),
    ({"qianchuan_output_spec": None}, {}),
    ({"qianchuan_output_spec": {}}, {}),
    ({"qianchuan_output_spec": {"resolution": "1440x2560"}},
     {"resolution": "1440x2560"}),
])
def test_output_spec_is_dictionary_and_preserves_explicit_settings(config, expected):
    tree = ast.parse(SOURCE.read_text())
    expressions = [value for node in ast.walk(tree) if isinstance(node, ast.Dict)
                   for key, value in zip(node.keys, node.values)
                   if isinstance(key, ast.Constant) and key.value == "qianchuan_output_spec"]
    assert len(expressions) == 1
    result = eval(compile(ast.Expression(expressions[0]), str(SOURCE), "eval"),
                  {"config": config})
    assert isinstance(result, dict)
    assert result == expected
