"""Remote GPU execution policy for the control-plane process.

The Mac process is a control plane only.  It may submit and download artifacts,
but must never execute media work locally or silently downgrade to another
provider.  Keep this module dependency-free so every worker boundary can use it.
"""
from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from urllib.parse import urlparse


class RemoteGpuRequiredError(RuntimeError):
    """Raised when a media operation would execute outside the remote GPU."""


@dataclass(frozen=True)
class ExecutionRecord:
    node: str
    service_url: str
    remote: bool


GPU_SERVICE_URL = os.environ.get("GPU_SERVICE_URL", "http://10.190.0.203:8877").rstrip("/")
GPU_EXECUTION_NODE = os.environ.get("GPU_EXECUTION_NODE", "remote-gpu")


def execution_record() -> ExecutionRecord:
    parsed = urlparse(GPU_SERVICE_URL)
    host = (parsed.hostname or "").lower()
    remote = host not in {"", "localhost", "127.0.0.1", "::1"}
    return ExecutionRecord(node=GPU_EXECUTION_NODE, service_url=GPU_SERVICE_URL, remote=remote)


def require_remote_gpu(operation: str) -> ExecutionRecord:
    """Validate the configured execution target before submitting a media job."""
    record = execution_record()
    if not record.remote:
        raise RemoteGpuRequiredError(f"{operation} requires a remote GPU service, not {record.service_url}")
    return record


def media_execution_node(operation: str) -> str:
    """Return the configured remote node marker for a media operation."""
    return require_remote_gpu(operation).node


def reject_local_media(operation: str) -> None:
    """Explicitly fail any attempted local media execution."""
    raise RemoteGpuRequiredError(f"local media execution is disabled: {operation}")
