"""Read-only backend listener diagnostics and safe startup guards.

This module deliberately has no process-management or recovery side effects.  It
only probes a listener and validates that a local bind is available before a
service manager starts the application.
"""

from __future__ import annotations

import errno
import logging
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ListenerDiagnostic:
    """Sanitized result of a TCP plus HTTP health probe."""

    classification: str
    host: str
    port: int
    http_status: int | None = None
    detail: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _endpoint(url: str) -> tuple[str, int, str]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        raise ValueError("health URL must be an HTTP(S) URL without credentials")
    if not parsed.hostname:
        raise ValueError("health URL must include a host")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/health"
    if parsed.query or parsed.fragment:
        path += ("?" + parsed.query) if parsed.query else ""
    return parsed.hostname, port, path


def probe_backend(
    health_url: str,
    *,
    timeout: float = 3.0,
    opener: Callable = urllib.request.urlopen,
    connector: Callable = socket.create_connection,
) -> ListenerDiagnostic:
    """Classify listener availability using read-only TCP and GET checks.

    The returned detail contains exception *types* only, avoiding credentials,
    task payloads, and potentially sensitive remote response bodies.
    """
    host, port, path = _endpoint(health_url)
    parsed = urllib.parse.urlparse(health_url)
    request_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))
    try:
        with connector((host, port), timeout=timeout):
            pass
    except socket.timeout:
        return ListenerDiagnostic("timeout", host, port, detail="TCP connection timed out")
    except OSError as exc:
        if exc.errno == errno.ECONNREFUSED:
            return ListenerDiagnostic("port_refused", host, port, detail="TCP connection refused")
        return ListenerDiagnostic("tcp_error", host, port, detail=type(exc).__name__)

    try:
        with opener(request_url, timeout=timeout) as response:
            status = getattr(response, "status", None)
            if status is None:
                status = response.getcode()
            if 200 <= status < 300:
                return ListenerDiagnostic("healthy", host, port, http_status=status)
            return ListenerDiagnostic("http_error", host, port, http_status=status)
    except urllib.error.HTTPError as exc:
        return ListenerDiagnostic("http_error", host, port, http_status=exc.code)
    except socket.timeout:
        return ListenerDiagnostic("http_timeout", host, port, detail="HTTP request timed out")
    except OSError as exc:
        return ListenerDiagnostic("http_error", host, port, detail=type(exc).__name__)
    except Exception as exc:  # urllib can wrap timeouts in implementation-specific errors
        logger.debug("Backend health probe failed: %s", type(exc).__name__)
        return ListenerDiagnostic("http_error", host, port, detail=type(exc).__name__)


def listener_available(host: str, port: int) -> bool:
    """Return whether *host:port* can be bound, without altering any service."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe_socket:
        probe_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe_socket.bind((host, port))
        except OSError as exc:
            if exc.errno in {errno.EADDRINUSE, errno.EACCES}:
                return False
            raise
    return True


def assert_listener_available(host: str, port: int) -> None:
    """Raise an actionable conflict error; never terminate an existing process."""
    if not listener_available(host, port):
        raise RuntimeError(
            f"Backend listener conflict on {host}:{port}; an existing process may be using the port. "
            "Inspect the owning process and stop/restart only with maintenance approval."
        )


def recovery_is_safe(*, active_tasks: int, qianchuan_tasks: int, approved: bool = False) -> bool:
    """Gate any future recovery action; defaults to no automation."""
    return bool(approved and active_tasks == 0 and qianchuan_tasks == 0)
