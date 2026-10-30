"""Run on 203 as susun after migration task stops; restores links to local copies."""
import hashlib
import json
import os
from pathlib import Path
import shutil

from migrate_c_media_to_222 import AUDIT, ROOT, DEST


def run():
    assert not (AUDIT / 'running.lock').exists(), 'Stop migration before rollback'
    rows = {}
    for line in (AUDIT / 'journal.jsonl').read_text(encoding='utf-8').splitlines():
        row = json.loads(line)
        if 'sha256' in row:
            rows[row['source']] = row
    for row in rows.values():
        source, target = Path(row['source']), Path(row['target'])
        assert source.is_relative_to(ROOT) and target.is_relative_to(DEST)
        original = source.with_name(source.name + '.migration-original')
        if original.exists():
            if source.is_symlink():
                source.unlink()
            assert not os.path.lexists(source)
            original.rename(source)
            continue
        if not source.is_symlink():
            continue
        assert os.path.normcase(str(source.resolve())) == os.path.normcase(str(target.resolve()))
        assert shutil.disk_usage(source.anchor).free > row['size'] + 5 * 2**30, 'Insufficient source-drive space'
        temporary = source.with_name(source.name + '.restore-partial')
        with target.open('rb') as inp, temporary.open('wb') as out:
            shutil.copyfileobj(inp, out, 8 * 1024 * 1024)
            out.flush()
            os.fsync(out.fileno())
        with temporary.open('rb') as f:
            assert hashlib.file_digest(f, 'sha256').hexdigest() == row['sha256']
        os.utime(temporary, ns=(row['mtime_ns'], row['mtime_ns']))
        os.replace(temporary, source)
    print('Rollback complete; destination copies retained')


if __name__ == '__main__':
    run()
