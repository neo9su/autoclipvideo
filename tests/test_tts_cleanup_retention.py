import ast
from pathlib import Path


def test_cleanup_keeps_results_until_consumer_has_had_time_to_download():
    tree = ast.parse(Path('gpu_service/main.py').read_text())
    helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_tts_cleanup_ready')
    ns = {}
    exec(compile(ast.Module(body=[helper], type_ignores=[]), 'cleanup', 'exec'), ns)
    ready = ns['_tts_cleanup_ready']
    assert not ready({'status': 'done', '_created_at': 0, '_finished_at': 9999}, now=10000)
    assert ready({'status': 'done', '_finished_at': 1}, now=10000)
    assert not ready({'status': 'processing', '_created_at': 0}, now=10000)
    assert not ready({'status': 'done'}, now=10000)
