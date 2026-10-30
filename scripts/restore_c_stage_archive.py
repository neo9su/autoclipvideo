"""Run on 203 with the verified archive copied locally; restore cleaned staging files."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile


def restore(archive):
    with tarfile.open(archive) as source:
        rows = json.load(source.extractfile('manifest.json'))
        roots = [Path(p) for p in [r'C:\douyin_login\_ststage',
                 r'C:\douyin_login\_stmodel.tar.gz',
                 r'C:\Users\neo\AppData\Local\Temp\3Kxl3behwLFVOjHMn3VXeiYgKS4',
                 r'C:\Users\neo\AppData\Local\Temp\nsy9415.tmp']]
        for row in rows:
            path = Path(row['path'])
            assert any(path == root or path.is_relative_to(root) for root in roots)
            if path.exists():
                with path.open('rb') as f:
                    assert hashlib.file_digest(f, 'sha256').hexdigest() == row['sha256']
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + '.restore.tmp')
            with source.extractfile(row['member']) as inp, temporary.open('xb') as out:
                shutil.copyfileobj(inp, out, 8 * 1024 * 1024)
            with temporary.open('rb') as f:
                assert hashlib.file_digest(f, 'sha256').hexdigest() == row['sha256']
            assert temporary.stat().st_size == row['size']
            os.replace(temporary, path)
            os.utime(path, ns=(row['mtime_ns'], row['mtime_ns']))
    print('Restored and verified staging files')


if __name__ == '__main__':
    restore(sys.argv[1])
