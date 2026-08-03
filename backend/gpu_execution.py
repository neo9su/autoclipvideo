"""Remote GPU execution policy for the control-plane process.

The Mac process is a control plane only.  It may submit and download artifacts,
but must never execute media work locally or silently downgrade to another
provider.  Keep this module dependency-free so every worker boundary can use it.
"""
from __future__ import annotations

import os
import platform
import time
from dataclasses import dataclass
from urllib.parse import urlparse


class RemoteGpuRequiredError(RuntimeError):
    """Raised when a media operation would execute outside the remote GPU."""


class GpuUnavailableError(RuntimeError):
    """Raised when a job must wait instead of falling back to local media work."""


@dataclass(frozen=True)
class ExecutionRecord:
    node: str
    service_url: str
    remote: bool


@dataclass
class TransferStats:
    """Control-plane transfer accounting for one logical media operation."""

    operation: str
    node: str
    input_bytes: int = 0
    output_bytes: int = 0
    upload_attempts: int = 0
    download_attempts: int = 0
    temporary_files: int = 0
    idempotency_key: str = ""
    started_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.started_at:
            self.started_at = time.time()

    @property
    def total_bytes(self) -> int:
        return self.input_bytes + self.output_bytes

    def as_dict(self) -> dict:
        return {
            "operation": self.operation,
            "execution_node": self.node,
            "input_bytes": self.input_bytes,
            "output_bytes": self.output_bytes,
            "upload_attempts": self.upload_attempts,
            "download_attempts": self.download_attempts,
            "temporary_files": self.temporary_files,
            "idempotency_key": self.idempotency_key,
            "total_bytes": self.total_bytes,
        }


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


def reject_local_media(operation: str) -> None:
    """Explicitly fail any attempted local media execution."""
    raise RemoteGpuRequiredError(f"local media execution is disabled: {operation}")


def media_execution_node(operation: str) -> str:
    """Return the validated remote execution node for job metadata."""
    return require_remote_gpu(operation).node



