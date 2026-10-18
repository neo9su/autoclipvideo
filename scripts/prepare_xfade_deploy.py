"""Prepare only the known legacy acrossfade defect and worker-error propagation."""
import ast
from pathlib import Path
from prepare_remote_audio_deploy import build as backup_runner

ROOT = Path(__file__).parents[1]


def build():
    source = (ROOT / 'gpu_service/main.py').read_text()
    tree = ast.parse(source)
    function = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_nvenc_xfade_merge')
    assignment = next(n for n in ast.walk(function) if isinstance(n, ast.Assign) and 'acrossfade=' in ast.unparse(n.value))
    new = '\n'.join(source.splitlines()[assignment.lineno - 1:assignment.end_lineno])
    old = '''            # Explicit acrossfade offset must match the video xfade offset so
            # audio and video stay locked across the merge (the old code left
            # the default, which drifted whenever A/V durations differed).
            fc = vf + f";[0:a][1:a]acrossfade=d={fade}:o={off:.3f}:c1=tri:c2=tri[aout]"'''
    new = '            # acrossfade o is a boolean; align audio spans to video first.\n' + new
    old_error = '''        if status == "error":
            logger.warning(f"GPU clip job {job_id} error: {data.get('error')}")
            return None'''
    new_error = '''        if status == "error":
            logger.warning(f"GPU clip job {job_id} error: {data.get('error')}")
            raise RuntimeError(f"Remote GPU clip job {job_id} failed: {data.get('error') or 'unknown worker error'}")'''
    plan = [
        (r'C:\Users\neo\douyin_processor\gpu_service\main.py', [(old, new)]),
        (r'C:\Users\neo\douyin_backend\gpu_service\main.py', [(old, new)]),
        (r'C:\Users\neo\douyin_backend\backend\editor.py', [(old_error, new_error)]),
    ]
    body = backup_runner().split('\n', 1)[1].replace("'remote-audio-'", "'xfade-fix-'")
    return 'PLAN = ' + repr(plan) + '\n' + body


if __name__ == '__main__':
    print(build())
