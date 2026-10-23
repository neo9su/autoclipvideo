import ast
import logging
from pathlib import Path

import pytest


def test_worker_failure_is_propagated_instead_of_local_fallback():
    source = Path(__file__).parents[1] / "backend" / "editor.py"
    tree = ast.parse(source.read_text())
    function = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
                    and n.name == "_edit_via_gpu")
    branch = next(n for n in ast.walk(function) if isinstance(n, ast.If)
                  and ast.unparse(n.test) == "status == 'error'")
    text = "def fixture():\n" + "\n".join("    " + line for line in ast.unparse(branch).splitlines())
    env = dict(status="error", job_id="test-job", data={"error": "xfade merge failed"},
               logger=logging.getLogger("test"))
    exec(text, env)
    with pytest.raises(RuntimeError, match="test-job.*xfade merge failed"):
        env["fixture"]()
