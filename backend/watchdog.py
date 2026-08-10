"""Control-plane helpers for the remote watchdog agent."""

from typing import Any

import httpx


async def ping_watchdog(url: str, timeout: float = 5.0) -> dict[str, Any]:
    """Return a stable health payload even when the remote agent is offline."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{url.rstrip('/')}/health")
            if response.status_code == 200:
                payload = response.json()
                if isinstance(payload, dict):
                    return {"ok": True, "reachable": True, **payload}
            return {"ok": False, "reachable": True, "status_code": response.status_code}
    except httpx.HTTPError as exc:
        return {"ok": False, "reachable": False, "error": type(exc).__name__}

