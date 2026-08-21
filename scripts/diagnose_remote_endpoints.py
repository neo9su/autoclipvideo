#!/usr/bin/env python3
"""Read-only reachability diagnosis for the remote Douyin services.

The probe performs only network observations: ICMP (when available), TCP
connect checks, and HTTP GET requests. It never starts, stops, kills, queues,
retries, or mutates a remote service.
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

DEFAULT_HOST = "10.190.0.203"
DEFAULT_PORTS = (8899, 8877)
DEFAULT_TIMEOUT_SECONDS = 3.0


@dataclass(frozen=True)
class ProbeResult:
    target: str
    kind: str
    observed_at: str
    ok: bool
    detail: str
    error_type: str | None = None
    http_status: int | None = None


def timestamp() -> str:
    """Return a timezone-aware UTC timestamp for evidence correlation."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def classify_socket_error(error: OSError) -> str:
    """Map platform socket failures to stable operator-facing categories."""
    message = str(error).lower()
    if "host is down" in message:
        return "host_down"
    if "connection refused" in message:
        return "connection_refused"
    if "timed out" in message or "timeout" in message:
        return "timeout"
    return error.__class__.__name__.lower()


def probe_tcp(host: str, port: int, timeout: float) -> ProbeResult:
    """Check one TCP endpoint without sending application data."""
    target = f"{host}:{port}"
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return ProbeResult(target, "tcp", timestamp(), True, "connect_succeeded")
    except OSError as error:
        error_type = classify_socket_error(error)
        return ProbeResult(target, "tcp", timestamp(), False, str(error), error_type)


def probe_http_get(url: str, timeout: float) -> ProbeResult:
    """Issue a GET request and retain only status/error metadata."""
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "douyin-readonly-diagnosis/1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return ProbeResult(url, "http_get", timestamp(), True, "response_received", http_status=response.status)
    except urllib.error.HTTPError as error:
        return ProbeResult(url, "http_get", timestamp(), True, "http_error_response", http_status=error.code)
    except urllib.error.URLError as error:
        reason = error.reason if isinstance(error.reason, OSError) else OSError(str(error.reason))
        return ProbeResult(url, "http_get", timestamp(), False, str(error.reason), classify_socket_error(reason))
    except OSError as error:
        return ProbeResult(url, "http_get", timestamp(), False, str(error), classify_socket_error(error))


def probe_ping(host: str, timeout: float) -> ProbeResult:
    """Run a bounded, non-mutating ICMP probe when the local ping supports it."""
    command = ["ping", "-c", "1", "-W", str(max(1, int(timeout * 1000))), host]
    started = timestamp()
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout + 1)
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        return ProbeResult(host, "icmp", started, False, str(error), "probe_unavailable")
    detail = "echo_reply" if completed.returncode == 0 else "no_echo_reply"
    return ProbeResult(host, "icmp", started, completed.returncode == 0, detail)


def collect_report(host: str, ports: tuple[int, ...], timeout: float) -> dict[str, Any]:
    """Collect a timestamped report using read-only probes only."""
    results: list[ProbeResult] = [probe_ping(host, timeout)]
    for port in ports:
        results.append(probe_tcp(host, port, timeout))
        results.append(probe_http_get(f"http://{host}:{port}/health", timeout))
    tcp_failures = [item.error_type for item in results if item.kind == "tcp" and not item.ok]
    host_or_network_failure = bool(tcp_failures) and all(
        failure in {"host_down", "timeout"} for failure in tcp_failures
    )
    return {
        "generated_at": timestamp(),
        "host": host,
        "ports": list(ports),
        "read_only": True,
        "classification": (
            "host_or_network_path_unreachable"
            if host_or_network_failure
            else "service_or_port_failure"
        ),
        "results": [asdict(item) for item in results],
        "limitations": [
            "A failed remote probe cannot prove whether Qianchuan or GPU work is still running.",
            "Do not infer an empty queue or inactive GPU from endpoint unreachability.",
        ],
    }


def parse_args() -> argparse.Namespace:
    """Parse safe, observation-only command-line options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--ports", nargs="+", type=int, default=list(DEFAULT_PORTS))
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def main() -> int:
    """Run the read-only probe and emit JSON evidence."""
    args = parse_args()
    if not args.host or not args.ports or any(port < 1 or port > 65535 for port in args.ports):
        raise SystemExit("host and valid TCP ports are required")
    if args.timeout <= 0:
        raise SystemExit("timeout must be positive")
    report = collect_report(args.host, tuple(args.ports), args.timeout)
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
