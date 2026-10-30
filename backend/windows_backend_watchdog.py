"""Recover the publishing backend only through its existing desktop task."""
import ctypes,subprocess,time,urllib.request
from pathlib import Path

TASK='DouyinBackend8899SusunInteractive'
LOG=Path(r'C:\douyin_login\_wd8899.log')
MISSES=Path(r'C:\douyin_login\_wd8899_miss.txt')

def log(message):
    with LOG.open('a',encoding='utf-8') as stream:
        stream.write(time.strftime('%Y-%m-%d %H:%M:%S ')+message+'\n')

def listeners():
    import psutil
    return sorted({c.pid for c in psutil.net_connections('tcp') if c.pid and c.status=='LISTEN' and c.laddr.port==8899})

def process_session(pid):
    value=ctypes.c_ulong()
    if not ctypes.windll.kernel32.ProcessIdToSessionId(pid,ctypes.byref(value)):
        raise OSError('Unable to determine backend session')
    return value.value

def healthy():
    try:
        with urllib.request.urlopen('http://127.0.0.1:8899/health',timeout=5) as response:
            return response.status==200
    except Exception:return False

def start_desktop_task():
    # The task uses InteractiveToken. There is deliberately no SYSTEM fallback.
    return subprocess.run(['schtasks','/Run','/TN',TASK],capture_output=True,
                          timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).returncode

def run_once(miss_limit=3):
    pids=listeners()
    if pids:
        MISSES.write_text('0')
        if len(pids)!=1:
            log('multiple-listeners: preserve running work; administrator check required')
            return 'conflict'
        session=process_session(pids[0])
        if session==0:
            log('blocked-session-0: preserve running work; no service-session restart allowed')
            return 'session0'
        state='healthy' if healthy() else 'listener-present-http-unavailable'
        log(f'{state}: pid={pids[0]} session={session}; no process stopped')
        return state
    try:misses=int(MISSES.read_text().strip())+1
    except (OSError,ValueError):misses=1
    MISSES.write_text(str(misses))
    if misses<miss_limit:
        log(f'listener-missing #{misses}: waiting for desktop supervisor')
        return 'waiting'
    result=start_desktop_task()
    log(f'listener-missing: requested desktop task {TASK}, result={result}; no SYSTEM fallback')
    if result==0:MISSES.write_text('0')
    return 'desktop-requested' if result==0 else 'desktop-login-required'

if __name__=='__main__':
    try:run_once()
    except Exception as exc:
        log('watchdog-check-failed: '+type(exc).__name__+'; no process stopped')
        raise
