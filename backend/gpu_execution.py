"""Control-plane media storage and SMB isolation guidance.

Recordings are job inputs and GPU outputs, not a public share. Keep the
recordings directory outside any macOS SMB export and expose only explicit
result downloads through the application.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


SHARED_STORAGE_MARKERS = ("smb", "cifs", "afp", "nfs")


def is_isolated_media_path(path: str) -> bool:
    """Return False for paths that look like mounted/shared storage."""
    normalized = str(Path(path).resolve()).lower()
    return not any(marker in normalized for marker in SHARED_STORAGE_MARKERS)


def media_storage_policy(recordings_dir: str, gpu_storage_dir: str) -> dict:
    """Describe the expected relationship between local inputs and GPU storage."""
    return {
        "recordings_dir": os.path.abspath(recordings_dir),
        "gpu_storage_dir": os.path.abspath(gpu_storage_dir),
        "recordings_isolated": is_isolated_media_path(recordings_dir),
        "gpu_storage_isolated": is_isolated_media_path(gpu_storage_dir),
        "recommendation": "Do not export recordings or gpu_storage via macOS SMB; use application downloads only.",
    }

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
