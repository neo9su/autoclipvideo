"""Minimal patch for the production-only persistent/batch encoder implementation."""


def patch(source):
    before='                    _embs = _encode_subprocess_batch(_texts)'
    after='                    _embs = await asyncio.to_thread(_encode_subprocess_batch, _texts)'
    if source.count(before)!=1:raise ValueError('Async fallback call drifted or already patched')
    source=source.replace(before,after,1)
    before='from srt_resolver import resolve_srt_path\n'
    if source.count(before)!=1:raise ValueError('Matcher import drifted')
    source=source.replace(before,before+'from encode_request_runner import run_encode_request\n',1)
    before='''            result = subprocess.run(
                [_VENV_PYTHON, _ENCODE_SCRIPT],
                input=req + "\\n",
                capture_output=True, text=True, timeout=20,
                encoding="utf-8", errors="replace"
            )'''
    if source.count(before)!=2:raise ValueError('One-shot IPC sites drifted')
    source=source.replace(before,'''            result = run_encode_request(
                [_VENV_PYTHON, _ENCODE_SCRIPT], req, timeout=20
            )''')
    compile(source,'director_matcher.py','exec');return source
