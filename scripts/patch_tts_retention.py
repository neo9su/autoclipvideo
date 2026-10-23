"""Apply/rollback the minimal TTS result retention patch on a deployed worker."""
import argparse
import ast
import hashlib
import json
from pathlib import Path


def patch(source):
    if 'def _tts_cleanup_ready(' in source:
        raise RuntimeError('already patched; verify deployed version before proceeding')
    helper = '''def _tts_cleanup_ready(job, now=None):
    """Retain fresh results while consumers download them."""
    if job.get("status") not in ("done", "error"):
        return False
    finished = job.get("_finished_at") or job.get("_created_at")
    if finished is None:
        return False
    return (time.time() if now is None else now) - finished >= 3600


'''
    edits = [('async def _cleanup_old_jobs():', helper + 'async def _cleanup_old_jobs():')]
    for status, old in [('done', '_tts_jobs[job_id].update({"status": "done", "output_path": out_path})'), ('error', '_tts_jobs[job_id].update({"status": "error", "error": err})')]:
        edits.append((old, old[:-2] + ', "_finished_at": time.time()})'))
    for old, new in edits:
        expected = 2 if old.startswith('_tts_jobs') and '"error"' in old else 1
        if source.count(old) != expected:
            raise RuntimeError('source drift: ' + old[:90])
        source = source.replace(old, new)
    start = source.index('    # Clean TTS outputs')
    end = source.index('    # Clean director temp dirs', start)
    block = source[start:end]
    old = 'if job.get("status") not in ("done", "error"):'
    if block.count(old) != 1:
        raise RuntimeError('disk cleanup source drift')
    source = source[:start] + block.replace(old, 'if not _tts_cleanup_ready(job):') + source[end:]
    start = source.index('    terminal_tts_ids = [')
    end = source.index('    for jid in terminal_tts_ids:', start)
    block = source[start:end]
    old = 'if j.get("status") in ("done", "error")'
    if block.count(old) != 1:
        raise RuntimeError('manual cleanup source drift')
    source = source[:start] + block.replace(old, 'if _tts_cleanup_ready(j)') + source[end:]
    ast.parse(source)
    return source


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['check', 'apply', 'rollback'])
    parser.add_argument('target', type=Path)
    parser.add_argument('backup_dir', type=Path)
    args = parser.parse_args()
    original = args.target.read_bytes()
    backup = args.backup_dir / args.target.name
    journal = args.backup_dir / 'journal.json'
    if args.mode == 'rollback':
        state = json.loads(journal.read_text(encoding='utf-8'))
        if digest(original) != state['after_sha256']:
            raise RuntimeError('target changed since deployment; refusing blind rollback')
        restored = backup.read_bytes()
        if digest(restored) != state['before_sha256']:
            raise RuntimeError('backup hash mismatch')
        args.target.write_bytes(restored)
        print('rolled back')
        return
    updated = patch(original.decode('utf-8')).encode('utf-8')
    if args.mode == 'check':
        print('patch anchors and syntax verified; no files changed')
        return
    args.backup_dir.mkdir(parents=True, exist_ok=True)
    with backup.open('xb') as stream:
        stream.write(original)
    with journal.open('x', encoding='utf-8') as stream:
        json.dump({'target': str(args.target), 'before_sha256': digest(original), 'after_sha256': digest(updated)}, stream, indent=2)
    args.target.write_bytes(updated)
    print('patched; backup and hash-checked rollback available')


if __name__ == '__main__':
    main()
