"""Bound one-shot encoder IPC without writing large Windows stdin pipes."""
import subprocess
import tempfile


def run_encode_request(command, request, timeout=20):
    # On Windows communicate(input=...) can block in _stdin_write before its
    # timeout wait begins. A finite, rewound file supplies the same JSON line
    # and lets communicate enforce the process deadline without a pipe writer.
    with tempfile.TemporaryFile(mode='w+b') as source:
        source.write((request+'\n').encode('utf-8'))
        source.seek(0)
        return subprocess.run(command, stdin=source, capture_output=True, text=True,
                              timeout=timeout, encoding='utf-8', errors='replace')
