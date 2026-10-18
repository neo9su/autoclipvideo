"""Hold a database-scoped OS lock before any lifespan startup side effects."""
from contextlib import asynccontextmanager, contextmanager
from functools import wraps
from pathlib import Path
import os


@contextmanager
def backend_instance_lock(path):
    path = Path(path)
    with path.open('a+b') as handle:
        if path.stat().st_size == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError('Another backend instance owns this database; startup skipped') from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    # Keep the file: unlinking creates races between old and new file handles.


def single_backend_instance(path):
    def decorate(lifespan):
        @asynccontextmanager
        @wraps(lifespan)
        async def guarded(*args, **kwargs):
            with backend_instance_lock(path):
                async with lifespan(*args, **kwargs) as state:
                    yield state
        return guarded
    return decorate
