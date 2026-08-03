"""Bounded Windows GPU service audit helpers.

The commands in this module are intended to run on the GPU host and use tail
reads only. They never kill a process without an explicit evidence review.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List


def tail_lines(path: Path, line_count: int = 200) -> List[str]:
    """Read only the final bounded number of lines without loading a huge log."""
    if line_count <= 0:
        raise ValueError("line_count must be positive")
    if not path.exists():
        return []
    with path.open("rb") as stream:
        stream.seek(0, 2)
        position = stream.tell()
        chunks: List[bytes] = []
        newline_count = 0
        while position > 0 and newline_count <= line_count:
            read_size = min(64 * 1024, position)
            position -= read_size
            stream.seek(position)
            chunk = stream.read(read_size)
            chunks.append(chunk)
            newline_count += chunk.count(b"\n")
    return b"".join(reversed(chunks)).decode("utf-8", errors="replace").splitlines()[-line_count:]


def audit_whisper_process(processes: Iterable[Dict[str, Any]], pid: int) -> Dict[str, Any]:
    """Classify a Whisper process from supplied evidence; never terminate it."""
    matches = [item for item in processes if int(item.get("pid", -1)) == pid]
    if not matches:
        return {"pid": pid, "found": False, "action": "observe"}
    process = matches[0]
    has_job_marker = bool(process.get("job_id") or process.get("input_path") or process.get("queue_entry"))
    return {
        "pid": pid,
        "found": True,
        "action": "retain" if has_job_marker else "manual_review",
        "has_job_evidence": has_job_marker,
        "evidence": {key: process.get(key) for key in ("command", "job_id", "input_path", "cpu_time") if process.get(key)},
    }


def render_service_report(status: Dict[str, Any], log_paths: Iterable[Path]) -> str:
    """Render an auditable status report from watchdog data and bounded logs."""
    lines = ["# GPU service stability audit", "", "## Service status"]
    for name, details in status.items():
        lines.append(f"- {name}: {json.dumps(details, ensure_ascii=False, sort_keys=True)}")
    lines.append("\n## Log tails")
    for path in log_paths:
        lines.append(f"\n### {path.name}")
        lines.extend(f"    {line}" for line in tail_lines(path))
    lines.append("\n## Policy\n- Do not kill Whisper without job evidence.\n- GPU failures wait for remote recovery; no macOS fallback.")
    return "\n".join(lines) + "\n"
