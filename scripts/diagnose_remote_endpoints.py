#!/usr/bin/env python3
"""Read-only reachability diagnosis for the remote backend and GPU services.

The command only opens TCP connections and performs HTTP GET requests.  It does
not restart services, mutate queues, submit work, or retry application jobs.
"""

from __future__ import annotations

import argparse
import datetime as dt
import errno
import json
import socket
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


DEFAULT_HOST = "10.190.0.203"
DEFAULT_ENDPOINTS = (("backend", 8899, "/api/monitor/status"), ("gpu", 8877, "/health"))


def utc_now() -> str:
    """Return a timezone-aware UTC timestamp suitable for evidence logs."""

    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def classify_socket_error(error: OSError) -> str:
    """Map common socket failures to stable, operator-friendly categories."""

    if error.errno in {errno.EHOSTDOWN, errno.ENETDOWN, errno.ENETUNREACH, errno.EHOSTUNREACH}:
        return "host_or_network_down"
    if error.errno in {errno.ECONNREFUSED, errno.ECONNRESET}:
        return "connection_refused_or_reset"
    if isinstance(error, socket.timeout) or error.errno in {errno.ETIMEDOUT, errno.EAGAIN}:
        return "timeout"
    if error.errno in {socket.EAI_AGAIN, socket.EAI_FAIL, socket.EAI_NONAME}:
        return "name_resolution_failure"
    return "socket_error"


@dataclass(frozen=True)
class ProbeResult:
    """Evidence for one endpoint at one point in time."""

    name: str
    host: str
    port: int
    path: str
    checked_at: str
    tcp_reachable: bool
    tcp_failure: str | None
    tcp_detail: str | None
    http_reachable: bool
    http_status: int | None
    http_failure: str | None
    http_detail: str | None


def probe_endpoint(name: str, host: str, port: int, path: str, timeout: float) -> ProbeResult:
    """Probe TCP and then a GET health endpoint without changing remote state."""

    checked_at = utc_now()
    tcp_reachable = False
    tcp_failure = None
    tcp_detail = None
    try:
        with socket.create_connection((host, port), timeout=timeout):
            tcp_reachable = True
    except OSError as error:
        tcp_failure = classify_socket_error(error)
        tcp_detail = str(error)

    http_reachable = False
    http_status = None
    http_failure = None
    http_detail = None
    request = urllib.request.Request(f"http://{host}:{port}{path}", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            http_status = response.status
            http_reachable = 200 <= response.status < 500
            if not http_reachable:
                http_failure = "unexpected_http_status"
    except urllib.error.HTTPError as error:
        http_status = error.code
        http_reachable = error.code < 500
        if not http_reachable:
            http_failure = "http_server_error"
        http_detail = str(error)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        reason = error.reason if isinstance(error, urllib.error.URLError) else error
        http_failure = classify_socket_error(reason) if isinstance(reason, OSError) else "http_error"
        http_detail = str(error)

    return ProbeResult(
        name=name,
        host=host,
        port=port,
        path=path,
        checked_at=checked_at,
        tcp_reachable=tcp_reachable,
        tcp_failure=tcp_failure,
        tcp_detail=tcp_detail,
        http_reachable=http_reachable,
        http_status=http_status,
        http_failure=http_failure,
        http_detail=http_detail,
    )


def diagnose_host(results: list[ProbeResult]) -> dict[str, Any]:
    """Summarize whether evidence points to host/network or service failure."""

    if not results:
        return {"classification": "no_observations", "confidence": "none"}
    tcp_failures = [item.tcp_failure for item in results if not item.tcp_reachable]
    if len(tcp_failures) == len(results) and any(
        failure == "host_or_network_down" for failure in tcp_failures
    ):
        return {
            "classification": "likely_host_or_network_failure",
            "confidence": "high",
            "reason": "both service ports failed before an application response",
        }
    if len(tcp_failures) == len(results) and all(
        failure == "connection_refused_or_reset" for failure in tcp_failures
    ):
        return {
            "classification": "host_reachable_but_services_not_accepting",
            "confidence": "medium",
            "reason": "both TCP connections were actively refused/reset",
        }
    if tcp_failures:
        return {
            "classification": "mixed_endpoint_failure",
            "confidence": "medium",
            "reason": "endpoint failures do not share one TCP failure mode",
        }
    return {
        "classification": "host_and_ports_reachable",
        "confidence": "high",
        "reason": "both TCP connections succeeded",
    }


def run_cycles(host: str, cycles: int, interval: float, timeout: float) -> list[dict[str, Any]]:
    """Collect independent read-only snapshots over the requested cycles."""

    snapshots = []
    for cycle in range(1, cycles + 1):
        results = [asdict(probe_endpoint(name, host, port, path, timeout)) for name, port, path in DEFAULT_ENDPOINTS]
        snapshots.append({"cycle": cycle, "checked_at": utc_now(), "results": results, "diagnosis": diagnose_host([ProbeResult(**item) for item in results])})
        if cycle < cycles:
            time.sleep(interval)
    return snapshots


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse and validate the intentionally read-only CLI options."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--interval", type=float, default=300.0, help="seconds between cycles")
    parser.add_argument("--timeout", type=float, default=5.0, help="per-connection timeout in seconds")
    parser.add_argument("--output", type=Path, help="write JSON evidence to this path")
    args = parser.parse_args(argv)
    if args.cycles < 1 or args.interval < 0 or args.timeout <= 0:
        parser.error("--cycles must be >= 1, --interval must be >= 0, and --timeout must be > 0")
    return args


def main(argv: list[str] | None = None) -> int:
    """Collect evidence and emit one JSON document to stdout or --output."""

    args = parse_args(argv or sys.argv[1:])
    evidence = {
        "tool": "diagnose_remote_endpoints",
        "mode": "read_only",
        "host": args.host,
        "cycles": run_cycles(args.host, args.cycles, args.interval, args.timeout),
    }
    payload = json.dumps(evidence, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
