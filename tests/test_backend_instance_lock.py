import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import subprocess
import sys
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / 'backend'))
from backend_instance_lock import backend_instance_lock, single_backend_instance


def probe(path):
    return subprocess.run([sys.executable, '-c',
        'from backend_instance_lock import backend_instance_lock; import sys\n'
        'with backend_instance_lock(sys.argv[1]): print("acquired")', str(path)],
        env={**__import__('os').environ, 'PYTHONPATH': str(Path(__file__).parents[1] / 'backend')},
        capture_output=True, text=True)


def test_process_exclusion_and_release(tmp_path):
    path = tmp_path / 'backend.lock'
    with backend_instance_lock(path):
        result = probe(path)
        assert result.returncode != 0
        assert 'Another backend instance' in result.stderr
    assert probe(path).returncode == 0
    assert path.exists()


def test_crashed_process_releases_lock(tmp_path):
    path = tmp_path / 'backend.lock'
    result = subprocess.run([sys.executable, '-c',
        'from backend_instance_lock import backend_instance_lock; import os,sys\n'
        'with backend_instance_lock(sys.argv[1]): os._exit(7)', str(path)],
        env={**__import__('os').environ, 'PYTHONPATH': str(Path(__file__).parents[1] / 'backend')})
    assert result.returncode == 7
    assert probe(path).returncode == 0


def test_lifespan_blocks_side_effects_and_releases_on_failure(tmp_path):
    path = tmp_path / 'backend.lock'
    calls = []
    @single_backend_instance(path)
    @asynccontextmanager
    async def lifespan():
        calls.append('startup')
        raise ValueError('startup failed')
        yield
    async def run():
        with backend_instance_lock(path):
            with pytest.raises(RuntimeError, match='Another backend'):
                async with lifespan(): pass
        assert calls == []
        with pytest.raises(ValueError, match='startup failed'):
            async with lifespan(): pass
        assert calls == ['startup']
        assert probe(path).returncode == 0
    asyncio.run(run())
