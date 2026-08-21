import errno
import socket
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

from service_manager import probe_backend, recovery_is_safe


def connector_refused(address, timeout):
    raise OSError(errno.ECONNREFUSED, "refused")


def connector_timeout(address, timeout):
    raise socket.timeout("timed out")


def connector_healthy(address, timeout):
    class ConnectedSocket:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    return ConnectedSocket()


class Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def opener_healthy(url, timeout):
    return Response()


def opener_http_error(url, timeout):
    raise urllib.error.HTTPError(url, 503, "unavailable", {}, None)


@pytest.mark.parametrize(
    ("connector", "expected"),
    [(connector_refused, "port_refused"), (connector_timeout, "timeout")],
)
def test_probe_classifies_tcp_failures(connector, expected):
    assert probe_backend("http://example.test:8899/health", connector=connector).classification == expected


def test_probe_classifies_http_error():
    diagnostic = probe_backend(
        "http://example.test:8899/health",
        connector=connector_healthy,
        opener=opener_http_error,
    )
    assert diagnostic.classification == "http_error"
    assert diagnostic.http_status == 503


def test_probe_classifies_healthy_response():
    diagnostic = probe_backend(
        "http://example.test:8899/health",
        connector=connector_healthy,
        opener=opener_healthy,
    )
    assert diagnostic.classification == "healthy"
    assert diagnostic.http_status == 200


def test_recovery_requires_approval_and_no_active_work():
    assert not recovery_is_safe(active_tasks=0, qianchuan_tasks=0)
    assert not recovery_is_safe(active_tasks=1, qianchuan_tasks=0, approved=True)
    assert not recovery_is_safe(active_tasks=0, qianchuan_tasks=1, approved=True)
    assert recovery_is_safe(active_tasks=0, qianchuan_tasks=0, approved=True)
