import errno
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from diagnose_remote_endpoints import ProbeResult, classify_socket_error, diagnose_host, parse_args


def make_result(name: str, tcp_reachable: bool, tcp_failure: str | None) -> ProbeResult:
    return ProbeResult(name, "example.invalid", 8899, "/health", "2026-08-21T04:01:00+00:00", tcp_reachable, tcp_failure, None, False, None, "http_error", None)


def test_classifies_host_down_and_refused_errors():
    assert classify_socket_error(OSError(errno.EHOSTDOWN, "Host is down")) == "host_or_network_down"
    assert classify_socket_error(ConnectionRefusedError(errno.ECONNREFUSED, "Connection refused")) == "connection_refused_or_reset"


def test_shared_host_down_failures_point_to_network_or_host():
    diagnosis = diagnose_host([make_result("backend", False, "host_or_network_down"), make_result("gpu", False, "host_or_network_down")])
    assert diagnosis["classification"] == "likely_host_or_network_failure"


def test_refused_ports_do_not_claim_host_is_down():
    diagnosis = diagnose_host([make_result("backend", False, "connection_refused_or_reset"), make_result("gpu", False, "connection_refused_or_reset")])
    assert diagnosis["classification"] == "host_reachable_but_services_not_accepting"


def test_cli_rejects_non_positive_timeout():
    try:
        parse_args(["--timeout", "0"])
    except SystemExit as error:
        assert error.code == 2
    else:
        raise AssertionError("expected argparse validation failure")
