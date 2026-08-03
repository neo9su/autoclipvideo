"""Safe GPU host audit helpers using bounded tail reads; never kills processes."""
from __future__ import annotations
import argparse
import json
import os
import re
from pathlib import Path

def tail_bytes(path: Path, limit: int = 256 * 1024) -> str:
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        stream.seek(max(0, stream.tell() - limit))
        return stream.read(limit).decode("utf-8", errors="replace")

def summarize_log(path: Path, limit: int = 256 * 1024) -> dict:
    text = tail_bytes(path, limit)
    patterns = {"tracebacks": r"Traceback \(most recent call last\)", "out_of_memory": r"out of memory|CUDA out of memory|OutOfMemoryError", "exceptions": r"\b(?:ERROR|CRITICAL|Exception|Error)\b", "exit_codes": r"(?:exit|return)\s*(?:code|status)?\s*[=:]\s*(-?\d+)"}
    summary = {name: len(re.findall(pattern, text, re.IGNORECASE)) for name, pattern in patterns.items()}
    summary["bytes_read"] = len(text.encode("utf-8")); summary["path"] = str(path)
    return summary

def audit_whisper_process(process_rows: list[dict], pid: int) -> dict:
    row = next((item for item in process_rows if int(item.get("pid", -1)) == pid), None)
    if row is None: return {"pid": pid, "conclusion": "not_found", "action": "none"}
    return {"pid": pid, "conclusion": "needs_job_correlation", "action": "do_not_kill", "process": row}

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", action="append", type=Path, default=[])
    parser.add_argument("--whisper-pid", type=int)
    parser.add_argument("--process-json", type=Path)
    args = parser.parse_args()
    report = {"logs": [summarize_log(path) for path in args.log if path.is_file()]}
    if args.whisper_pid is not None:
        rows = json.loads(args.process_json.read_text(encoding="utf-8")) if args.process_json else []
        report["whisper"] = audit_whisper_process(rows, args.whisper_pid)
    print(json.dumps(report, ensure_ascii=False, indent=2)); return 0

if __name__ == "__main__": raise SystemExit(main())
