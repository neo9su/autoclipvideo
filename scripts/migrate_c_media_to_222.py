"""Run as susun on 203. Copy stable local media to disk2; verify before linking."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import time

ROOT = Path(r'C:\Users\neo\douyin_backend')
AUDIT = ROOT / 'codex_rollbacks' / 'media-to-222-20261024'
DEST = Path(r'\\10.190.0.222\disk2\douyin-203-c-media')
ROOTS = ['recordings', 'voice_output', 'qianchuan_uploads', 'media_overflow']


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def journal(row):
    with (AUDIT / 'journal.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')
        f.flush()
        os.fsync(f.fileno())


def save(state):
    temp = AUDIT / 'status.writing'
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, AUDIT / 'status.json')


def files(root):
    pending = [root]
    while pending:
        parent = pending.pop()
        with os.scandir(parent) as entries:
            for entry in entries:
                metadata = entry.stat(follow_symlinks=False)
                if metadata.st_file_attributes & 1024:
                    continue
                path = Path(entry.path)
                if stat.S_ISDIR(metadata.st_mode):
                    pending.append(path)
                elif stat.S_ISREG(metadata.st_mode):
                    yield path


def run():
    AUDIT.mkdir(parents=True, exist_ok=True)
    lock = AUDIT / 'running.lock'
    with lock.open('x') as f:
        f.write(str(os.getpid()))
    state = dict(phase='preflight', migrated_files=0, migrated_bytes=0, skipped=0, errors=0)
    try:
        assert os.environ.get('USERNAME', '').lower() == 'susun'
        DEST.mkdir(parents=True, exist_ok=True)
        probe = DEST / 'write-probe.tmp'
        probe.write_bytes(b'203 media migration probe')
        link = AUDIT / 'link-probe.tmp'
        os.symlink(str(probe), str(link))
        assert link.read_bytes() == probe.read_bytes()
        link.unlink()
        probe.unlink()
        state['phase'] = 'migrating'
        save(state)
        for folder in ROOTS:
            source_root = ROOT / folder
            for source in files(source_root):
                if source.name.endswith(('.migration-original', '.migration-link')):
                    raise RuntimeError('Interrupted switch detected; recover from journal first')
                stat = source.stat()
                if time.time() - stat.st_mtime < 1800:
                    state['skipped'] += 1
                    continue
                target = DEST / folder / source.relative_to(source_root)
                row = dict(source=str(source), target=str(target), size=stat.st_size, mtime_ns=stat.st_mtime_ns)
                state['current_file'] = str(source)
                save(state)
                try:
                    assert shutil.disk_usage(DEST).free > stat.st_size + 10 * 2**30
                    target.parent.mkdir(parents=True, exist_ok=True)
                    original_hash = digest(source)
                    row['sha256'] = original_hash
                    if target.exists():
                        assert target.stat().st_size == stat.st_size and digest(target) == original_hash, 'Destination conflict'
                    else:
                        partial = target.with_name(target.name + '.migration-partial')
                        with source.open('rb') as inp, partial.open('wb') as out:
                            shutil.copyfileobj(inp, out, 8 * 1024 * 1024)
                            out.flush()
                            os.fsync(out.fileno())
                        assert partial.stat().st_size == stat.st_size and digest(partial) == original_hash
                        os.utime(partial, ns=(stat.st_atime_ns, stat.st_mtime_ns))
                        os.replace(partial, target)
                    now = source.stat()
                    assert now.st_size == stat.st_size and now.st_mtime_ns == stat.st_mtime_ns
                    assert digest(source) == original_hash, 'Source changed while copying'
                    temporary_link = source.with_name(source.name + '.migration-link')
                    original = source.with_name(source.name + '.migration-original')
                    assert not os.path.lexists(temporary_link) and not original.exists()
                    os.symlink(str(target), str(temporary_link))
                    assert temporary_link.stat().st_size == stat.st_size
                    journal(dict(row, phase='verified-before-switch'))
                    source.rename(original)
                    try:
                        os.replace(temporary_link, source)
                        assert source.is_symlink() and source.stat().st_size == stat.st_size
                    except BaseException:
                        if os.path.lexists(source):
                            source.unlink()
                        original.rename(source)
                        if os.path.lexists(temporary_link):
                            temporary_link.unlink()
                        raise
                    journal(dict(row, phase='linked-original-retained'))
                    original.unlink()
                    journal(dict(row, phase='complete'))
                    state['migrated_files'] += 1
                    state['migrated_bytes'] += stat.st_size
                except Exception as exc:
                    state['errors'] += 1
                    journal(dict(row, phase='error', error=str(exc)))
                state['C_free_bytes'] = shutil.disk_usage('C:\\').free
                save(state)
        state['phase'] = 'finished'
    except BaseException as exc:
        state.update(phase='failed', error=str(exc))
        raise
    finally:
        save(state)
        lock.unlink(missing_ok=True)


if __name__ == '__main__':
    run()
