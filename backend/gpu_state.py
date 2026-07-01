"""
GPU service availability watcher + watchdog auto-start.

Runs as a lightweight background task. Probes GPU service health with
exponential backoff. After AUTO_START_AFTER seconds offline it asks the
watchdog agent to restart the service, then continues probing.

Usage:
    asyncio.create_task(watch_gpu_service(broadcast_fn=broadcast))

    if not is_online():
        await asyncio.wait_for(wait_until_online(), timeout=300)
"""

import asyncio
import logging
import os
import time

import aiohttp
import httpx

from notifier import notify

logger = logging.getLogger(__name__)

GPU_SERVICE_URL = os.environ.get("GPU_SERVICE_URL", "http://10.190.0.203:8877")
COMFYUI_URL     = os.environ.get("COMFYUI_URL",     "http://10.190.0.203:8188")
WATCHDOG_URL    = os.environ.get("WATCHDOG_URL",    "http://10.190.0.203:8878")

# Auto-start: trigger watchdog this many seconds after detecting offline
AUTO_START_AFTER    = 60    # first attempt after 1 min offline
AUTO_START_COOLDOWN = 300   # minimum gap between consecutive auto-start calls

# ── shared state ──────────────────────────────────────────────────────────────
_online: bool = False
_event: asyncio.Event = asyncio.Event()  # set = online, cleared = offline
_offline_since: float = 0.0             # monotonic timestamp when outage started
_consecutive_failures: int = 0          # probe failure counter for hysteresis
_CONSECUTIVE_OFFLINE_THRESHOLD = 3      # require N consecutive failures to flip offline
_CONSECUTIVE_ONLINE_THRESHOLD = 2       # require N consecutive successes to flip back online
_consecutive_successes: int = 0         # probe success counter for hysteresis

# Maintenance mode: when True, all GPU pipeline calls are skipped / fallback to local
_maintenance: bool = False

# Watchdog agent state (updated by the watcher loop)
_watchdog_available: bool = False
_watchdog_services: dict = {}           # {name: {running, healthy, pid, uptime_s}}

# Callbacks fired when GPU transitions from offline → online
_online_callbacks: list = []


def register_online_callback(fn) -> None:
    """Register an async callback fn() to be called when GPU comes back online."""
    if fn not in _online_callbacks:
        _online_callbacks.append(fn)


def is_online() -> bool:
    return _online and not _maintenance


def is_maintenance() -> bool:
    return _maintenance


def set_maintenance(value: bool) -> None:
    global _maintenance, _online
    _maintenance = value
    if value:
        # Treat as offline so callers skip GPU immediately
        _event.clear()
        logger.info("GPU maintenance mode ENABLED — all GPU pipelines will skip/fallback")
    else:
        # Restore event state based on actual connectivity
        if _online:
            _event.set()
        logger.info("GPU maintenance mode DISABLED")


def watchdog_status() -> dict:
    return {
        "available": _watchdog_available,
        "services": _watchdog_services,
    }


async def wait_until_online() -> None:
    """Suspend until the GPU service is reachable."""
    await _event.wait()


# ── internal helpers ─────────────────────────────────────────────────────────

def _probe_gpu_sync() -> bool:
    """Synchronous GPU probe — runs in a thread to avoid event-loop deadlocks."""
    try:
        r = httpx.get(f"{GPU_SERVICE_URL}/health", timeout=15)
        return r.status_code == 200
    except Exception as e:
        logger.warning(f"GPU probe error: {type(e).__name__}: {e}")
        return False


async def _probe_gpu() -> bool:
    """Async wrapper that runs the sync probe in a thread."""
    return await asyncio.to_thread(_probe_gpu_sync)


async def _probe_watchdog(client: httpx.AsyncClient) -> tuple[bool, dict]:
    """Return (available, services_dict)."""
    try:
        r = await client.get(f"{WATCHDOG_URL}/status", timeout=5.0)
        if r.status_code == 200:
            return True, r.json()
        return False, {}
    except Exception:
        return False, {}


async def _watchdog_start(client: httpx.AsyncClient, service: str) -> bool:
    """Ask watchdog agent to start a service. Returns True on success."""
    try:
        r = await client.post(f"{WATCHDOG_URL}/start/{service}", timeout=10.0)
        ok = r.status_code == 200
        if ok:
            logger.info(f"Watchdog: start '{service}' accepted → {r.json()}")
        else:
            logger.warning(f"Watchdog: start '{service}' failed {r.status_code}: {r.text[:200]}")
        return ok
    except Exception as e:
        logger.debug(f"Watchdog unreachable for start '{service}': {e}")
        return False


# ── public background task ───────────────────────────────────────────────────

async def watch_gpu_service(broadcast_fn=None) -> None:
    """
    Main watcher loop.

    GPU probe intervals:
      online  → ONLINE_INTERVAL (30 s)
      offline → exponential backoff MIN_BACKOFF..MAX_BACKOFF (10 s → 5 min)

    Auto-start behaviour:
      • After AUTO_START_AFTER seconds offline, call watchdog /start/gpu
      • Repeat at AUTO_START_COOLDOWN intervals while still offline
      • Also probe watchdog /status every WATCHDOG_INTERVAL seconds
    """
    global _online, _offline_since, _watchdog_available, _watchdog_services

    ONLINE_INTERVAL   = 30
    MIN_BACKOFF       = 10
    MAX_BACKOFF       = 300
    WATCHDOG_INTERVAL = 60   # how often to refresh watchdog /status

    backoff          = MIN_BACKOFF
    last_reminder    = 0.0
    last_autostart   = 0.0   # monotonic time of last /start/gpu call
    last_watchdog_poll = 0.0
    first_probe      = True

    while True:
        try:
            global _online, _offline_since, _consecutive_failures, _consecutive_successes
            now = time.monotonic()
            logger.info(f"watcher loop tick #{int(now)}")

            # ── skip probe entirely while in maintenance mode ───────
            if _maintenance:
                await asyncio.sleep(ONLINE_INTERVAL)
                continue

            # ── probe GPU service (threaded sync, avoids event-loop deadlock) ──
            online = await _probe_gpu()
            logger.info(f"probe returned online={online}, _online before={_online}")

            if first_probe and not online:
                _offline_since = now
                last_reminder  = now
            first_probe = False

            if online:
                # Reset failure counter on any successful probe
                _consecutive_failures = 0

            if online:
                _consecutive_successes += 1
            else:
                _consecutive_successes = 0

            if online and not _online:
                # came back online
                _online = True
                _event.set()
                down = int(now - _offline_since) if _offline_since else 0
                logger.info(f"GPU service online ✓" + (f" (was down {down}s)" if down else ""))
                if broadcast_fn:
                    await _safe_broadcast(broadcast_fn, {"type": "gpu_online"})
                if down > 60:
                    asyncio.create_task(notify(
                        f"✅ GPU服务器已恢复上线（离线了 {down//60} 分 {down%60} 秒）"
                    ))
                backoff = MIN_BACKOFF
                last_autostart = 0.0  # reset so next outage triggers fresh
                # Fire recovery callbacks (e.g. auto-retry failed clip jobs)
                for _cb in list(_online_callbacks):
                    try:
                        asyncio.create_task(_cb())
                    except Exception:
                        pass

            elif not online and _online:
                # Count consecutive failures before flipping offline
                _consecutive_failures += 1
                _consecutive_successes = 0
                if _consecutive_failures >= _CONSECUTIVE_OFFLINE_THRESHOLD:
                    _online = False
                    _event.clear()
                    _offline_since = now
                    last_reminder  = now
                    logger.warning(f"GPU service offline ({GPU_SERVICE_URL}) — {_consecutive_failures} consecutive failures")
                    if broadcast_fn:
                        await _safe_broadcast(broadcast_fn, {"type": "gpu_offline", "since": 0})
                else:
                    logger.debug(f"GPU probe failed ({_consecutive_failures}/{_CONSECUTIVE_OFFLINE_THRESHOLD}) — still considered online")

            elif not online:
                # still offline
                down = int(now - _offline_since)

                # periodic log reminder
                if now - last_reminder >= MAX_BACKOFF:
                    logger.warning(f"GPU service still offline ({down}s)")
                    if broadcast_fn:
                        await _safe_broadcast(broadcast_fn, {"type": "gpu_offline", "since": down})
                    last_reminder = now
                    # 离线超过5分钟时告警（每5分钟最多发一次）
                    if down >= 300 and down % 300 < MAX_BACKOFF:
                        asyncio.create_task(notify(
                            f"⚠️ GPU服务器离线已 {down//60} 分钟 ({GPU_SERVICE_URL})"
                        ))

                # auto-start via watchdog
                if (down >= AUTO_START_AFTER
                        and now - last_autostart >= AUTO_START_COOLDOWN):
                    logger.info(f"GPU offline {down}s — asking watchdog to start")
                    # Create httpx client locally for watchdog calls
                    async with httpx.AsyncClient() as wd_client:
                        started = await _watchdog_start(wd_client, "gpu")
                    last_autostart = now
                    if started and broadcast_fn:
                        await _safe_broadcast(broadcast_fn, {
                            "type": "watchdog_start", "service": "gpu"
                        })

            # ── poll watchdog status (less frequently) ───────────────
            if now - last_watchdog_poll >= WATCHDOG_INTERVAL:
                async with httpx.AsyncClient() as wd_client:
                    avail, svcs = await _probe_watchdog(wd_client)
                changed = (avail != _watchdog_available)
                _watchdog_available = avail
                _watchdog_services  = svcs
                last_watchdog_poll  = now
                if changed and broadcast_fn:
                    await _safe_broadcast(broadcast_fn, {
                        "type": "watchdog_status",
                        "available": avail,
                        "services": svcs,
                    })

            interval = ONLINE_INTERVAL if online else min(backoff, MAX_BACKOFF)
            if not online:
                backoff = min(backoff * 2, MAX_BACKOFF)

        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.exception(f"GPU watcher error: {e}")
            interval = backoff

        await asyncio.sleep(interval)


async def _safe_broadcast(fn, msg: dict) -> None:
    try:
        await fn(msg)
    except Exception:
        pass
