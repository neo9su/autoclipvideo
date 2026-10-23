import ast
from pathlib import Path


def load_counter(**registries):
    source = Path(__file__).parents[1] / "gpu_service" / "main.py"
    tree = ast.parse(source.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == "_active_media_job_counts")
    env = dict(registries)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), env)
    return env["_active_media_job_counts"]


def test_director_and_tts_activity_is_visible_when_clip_queue_empty():
    counts = load_counter(_clip_jobs={}, _director_jobs={"d": {"status": "processing"}},
                          _tts_jobs={"t": {"status": "queued"}})()
    assert counts["clip"] == 0
    assert counts["director"] == counts["tts"] == 1


def test_terminal_history_does_not_block_maintenance():
    jobs = {s: {"status": s} for s in ["done", "error", "cancelled", "canceled"]}
    assert all(v == 0 for v in load_counter(_jobs=jobs)().values())


def test_unknown_and_missing_states_fail_closed():
    assert load_counter(_audio_concat_jobs={"a": {}, "b": {"status": "new-state"}})()["audio_concat"] == 2


def test_processing_concat_is_counted():
    assert load_counter(_concat_jobs={"c": {"status": "processing"}})()["concat"] == 1
