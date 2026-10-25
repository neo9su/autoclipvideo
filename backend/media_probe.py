"""CPU-only container metadata checks; slow I/O is not proof of corrupt media."""
import asyncio
import math
import os
import subprocess

PROBE_TIMEOUT = 30.0
TRANSIENT_PROBE_PREFIX = 'media probe pending:'

async def validate_mp4(filepath):
    command = ['ffprobe','-v','error','-show_entries','format=duration',
               '-of','default=noprint_wrappers=1:nokey=1',filepath]
    proc = None
    try:
        kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
        proc = await asyncio.create_subprocess_exec(*command,stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE,**kwargs)
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=PROBE_TIMEOUT)
        if proc.returncode:
            return False, 'invalid mp4: '+stderr.decode(errors='replace').strip()[-200:]
        try:
            duration = float(stdout.decode().strip())
        except (ValueError, UnicodeError):
            return False, 'invalid mp4: bad duration'
        if not math.isfinite(duration) or duration <= 0:
            return False, 'invalid mp4: duration is not positive and finite'
        return True, ''
    except asyncio.TimeoutError:
        if proc is not None:
            try: proc.kill()
            except ProcessLookupError: pass
            await proc.communicate()
        return False, f'{TRANSIENT_PROBE_PREFIX} ffprobe timeout (>{PROBE_TIMEOUT:g}s)'
    except OSError as exc:
        return False, f'{TRANSIENT_PROBE_PREFIX} {type(exc).__name__}: {exc}'
