"""Preflight guards must fail before importing heavyweight model dependencies."""
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'audit_wig_visual.py'


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True)


def test_existing_report_is_never_overwritten(tmp_path):
    image = tmp_path / 'frame.jpg'
    image.write_bytes(b'source bytes')
    report = tmp_path / 'report.json'
    report.write_bytes(b'prior evidence')
    r = run('--image', image, '--output', report, '--cache-dir', tmp_path / 'cache')
    assert r.returncode != 0
    assert 'FileExistsError' in r.stderr
    assert report.read_bytes() == b'prior evidence'
    assert image.read_bytes() == b'source bytes'
    assert not (tmp_path / 'cache').exists()


def test_bounded_explicit_input(tmp_path):
    image = tmp_path / 'frame.jpg'
    image.touch()
    args = ['--output', tmp_path / 'out.json', '--cache-dir', tmp_path / 'cache']
    for _ in range(13):
        args += ['--image', image]
    r = run(*args)
    assert r.returncode != 0
    assert 'at most 12' in r.stderr
    assert not (tmp_path / 'out.json').exists()


def test_missing_source_cannot_create_report(tmp_path):
    r = run('--image', tmp_path / 'missing.jpg', '--output', tmp_path / 'out.json', '--cache-dir', tmp_path / 'cache')
    assert r.returncode != 0
    assert not (tmp_path / 'out.json').exists()
