"""
Watchdog Agent — runs on the Windows GPU server (10.190.0.203:8878).

Place this file on the GPU server alongside watchdog_config.json and start it
once at system boot (e.g. via Task Scheduler or a .bat shortcut in Startup):

    pythonw watchdog_agent.py        # hidden window
    python  watchdog_agent.py        # visible window

It exposes a tiny HTTP API so the Mac backend can start/stop/query services:

    GET  /health                     → {"status": "ok"}
    GET  /status                     → {service: {running, pid, uptime_s}, ...}
    POST /start/{service}            → start if not running
    POST /stop/{service}             → kill process
    POST /restart/{service}          → stop then start

watchdog_config.json example
─────────────────────────────
{
  "port": 8878,
  "services": {
    "gpu": {
      "name": "GPU转录服务",
      "cmd": ["python", "server.py"],
      "cwd": "C:\\\\gpu-service",
      "health_url": "http://localhost:8877/health",
      "enabled": true
    },
    "comfyui": {
      "name": "ComfyUI",
      "cmd": ["python", "main.py", "--listen", "0.0.0.0", "--port", "8188"],
      "cwd": "C:\\\\ComfyUI",
      "health_url": "http://localhost:8188/system_stats",
      "enabled": true
    }
  }
}
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, Optional

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s watchdog: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("watchdog.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

CONFIG_FILE = Path(__file__).parent / "watchdog_config.json"

DEFAULT_CONFIG = {
    "port": 8878,
    "monitor_interval": 30,    # seconds between health checks
    "restart_cooldown": 120,   # min seconds between auto-restarts per service
    "services": {
        "gpu": {
            "name": "GPU转录服务",
            "cmd": ["python", "server.py"],
            "cwd": "C:\\gpu-service",
            "health_url": "http://localhost:8877/health",
            "enabled": True,
        },
        "comfyui": {
            "name": "ComfyUI",
            "cmd": ["python", "main.py", "--listen", "0.0.0.0", "--port", "8188"],
            "cwd": "C:\\ComfyUI",
            "health_url": "http://localhost:8188/system_stats",
            "enabled": True,
        },
    },
}


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
            logger.info(f"Config loaded from {CONFIG_FILE}")
            return cfg
        except Exception as e:
            logger.error(f"Config load error: {e}, using defaults")
    else:
        # Write default config so user can edit it
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
        logger.info(f"Default config written to {CONFIG_FILE} — edit paths before use")
    return DEFAULT_CONFIG


config = load_config()
SERVICES: dict = config.get("services", DEFAULT_CONFIG["services"])
PORT: int = config.get("port", 8878)
MONITOR_INTERVAL: int = config.get("monitor_interval", 30)
RESTART_COOLDOWN: int  = config.get("restart_cooldown", 120)

# ── Process registry ──────────────────────────────────────────────────────────

_procs: Dict[str, subprocess.Popen] = {}   # service_name → Popen
_start_times: Dict[str, float] = {}        # service_name → monotonic start time
_restart_counts: Dict[str, int] = {}       # service_name → auto-restart count
_last_restart: Dict[str, float] = {}       # service_name → monotonic time of last restart


def _is_running(name: str) -> tuple[bool, Optional[int]]:
    """Return (is_running, pid). Cleans up dead processes."""
    proc = _procs.get(name)
    if proc is None:
        return False, None
    if proc.poll() is None:          # still running
        return True, proc.pid
    del _procs[name]                 # process exited
    _start_times.pop(name, None)
    return False, None


def _start(name: str) -> dict:
    svc = SERVICES.get(name)
    if not svc:
        return {"ok": False, "error": f"Unknown service: {name}"}

    running, pid = _is_running(name)
    if running:
        return {"ok": True, "status": "already_running", "pid": pid}

    cmd  = svc["cmd"]
    cwd  = svc.get("cwd", ".")
    if not os.path.isdir(cwd):
        return {"ok": False, "error": f"Working directory not found: {cwd}"}

    try:
        flags = 0
        if sys.platform == "win32":
            # Detach from agent's console; process survives if agent window is closed
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            creationflags=flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        _procs[name] = proc
        _start_times[name] = time.monotonic()
        logger.info(f"Started {svc['name']} (pid={proc.pid}) cmd={cmd} cwd={cwd}")
        return {"ok": True, "status": "started", "pid": proc.pid}
    except Exception as e:
        logger.error(f"Failed to start {name}: {e}")
        return {"ok": False, "error": str(e)}


def _stop(name: str) -> dict:
    svc = SERVICES.get(name)
    if not svc:
        return {"ok": False, "error": f"Unknown service: {name}"}

    running, pid = _is_running(name)
    if not running:
        return {"ok": True, "status": "not_running"}

    try:
        proc = _procs[name]
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        del _procs[name]
        _start_times.pop(name, None)
        logger.info(f"Stopped {svc['name']} (pid={pid})")
        return {"ok": True, "status": "stopped", "pid": pid}
    except Exception as e:
        logger.error(f"Failed to stop {name}: {e}")
        return {"ok": False, "error": str(e)}


# ── Health probe ──────────────────────────────────────────────────────────────

async def _probe_health(health_url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(health_url)
            return r.status_code == 200
    except Exception:
        return False


# ── Auto-monitor ─────────────────────────────────────────────────────────────

async def _ensure_service(name: str) -> None:
    """Start the service if it is not already running or reachable."""
    svc = SERVICES.get(name)
    if not svc or not svc.get("enabled", True):
        return

    running, _ = _is_running(name)

    # If not in our process registry, check the health URL before assuming it's down.
    # It may have been started externally (e.g. by the user or a bat script).
    if not running:
        health_url = svc.get("health_url")
        if health_url and await _probe_health(health_url):
            return   # alive externally — leave it alone
        now = time.monotonic()
        if now - _last_restart.get(name, 0) >= RESTART_COOLDOWN:
            logger.warning(f"[monitor] '{name}' not running — starting")
            result = _start(name)
            if result.get("ok"):
                _restart_counts[name] = _restart_counts.get(name, 0) + 1
                _last_restart[name] = now
        return

    # Process is running — check health URL
    health_url = svc.get("health_url")
    if not health_url:
        return
    if await _probe_health(health_url):
        return

    now = time.monotonic()
    if now - _last_restart.get(name, 0) >= RESTART_COOLDOWN:
        logger.warning(f"[monitor] '{name}' running but unhealthy — restarting")
        _stop(name)
        await asyncio.sleep(3)
        result = _start(name)
        if result.get("ok"):
            _restart_counts[name] = _restart_counts.get(name, 0) + 1
            _last_restart[name] = now


async def _monitor_loop() -> None:
    """Background task: periodically health-check and auto-restart all enabled services."""
    logger.info(f"Auto-monitor started (interval={MONITOR_INTERVAL}s, cooldown={RESTART_COOLDOWN}s)")
    while True:
        await asyncio.sleep(MONITOR_INTERVAL)
        for name in list(SERVICES):
            try:
                await _ensure_service(name)
            except Exception as e:
                logger.debug(f"[monitor] error checking '{name}': {e}")


async def _startup_services() -> None:
    """On watchdog startup, start any enabled services that are not already running."""
    logger.info("Starting enabled services...")
    for name in list(SERVICES):
        try:
            await _ensure_service(name)
        except Exception as e:
            logger.error(f"Startup error for '{name}': {e}")


# ── FastAPI app ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await _startup_services()
    monitor_task = asyncio.create_task(_monitor_loop())
    yield
    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Watchdog Agent", docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "services": list(SERVICES.keys())}


@app.get("/status")
async def status():
    result = {}
    for name, svc in SERVICES.items():
        running, pid = _is_running(name)
        uptime = int(time.monotonic() - _start_times[name]) if (running and name in _start_times) else 0
        # If not in our registry, check health URL — may be externally started
        healthy = False
        health_url = svc.get("health_url")
        if health_url:
            healthy = await _probe_health(health_url)
            if healthy and not running:
                running = True   # alive externally
        last_r = _last_restart.get(name)
        result[name] = {
            "name": svc["name"],
            "running": running,
            "healthy": healthy,
            "pid": pid,
            "uptime_s": uptime,
            "enabled": svc.get("enabled", True),
            "restart_count": _restart_counts.get(name, 0),
            "last_restart_ago": int(time.monotonic() - last_r) if last_r else None,
        }
    return result


@app.post("/start/{name}")
def start_service(name: str):
    if name not in SERVICES:
        raise HTTPException(404, f"Unknown service: {name}")
    result = _start(name)
    if not result["ok"]:
        raise HTTPException(500, result.get("error", "Failed"))
    return result


@app.post("/stop/{name}")
def stop_service(name: str):
    if name not in SERVICES:
        raise HTTPException(404, f"Unknown service: {name}")
    return _stop(name)


@app.post("/restart/{name}")
async def restart_service(name: str):
    if name not in SERVICES:
        raise HTTPException(404, f"Unknown service: {name}")
    _stop(name)
    await asyncio.sleep(2)
    result = _start(name)
    if not result["ok"]:
        raise HTTPException(500, result.get("error", "Failed"))
    return result


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info(f"Watchdog agent starting on port {PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
