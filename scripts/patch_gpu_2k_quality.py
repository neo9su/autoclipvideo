"""Patch the GPU director service to render and verify requested 2K output."""
from __future__ import annotations

import argparse
import py_compile
import shutil
from pathlib import Path


def patch(path: Path, backup_dir: Path) -> None:
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup_dir / f"{path.parent.parent.name}_{path.name}")
    text = path.read_text(encoding="utf-8-sig")
    if "\nimport re\n" not in text:
        text = text.replace("import logging\n", "import logging\nimport re\n", 1)
    text = text.replace(
        'created_at=time.time())',
        'created_at=time.time(), requested_output_spec=dict(req.qianchuan_output_spec or {}))',
        1,
    )
    old = '    return {**probe, "ok": not probe["errors"], "execution_node": "remote-gpu", "job_id": job_id}\n'
    new = '''    spec = job.get("requested_output_spec") or {}
    resolution = str(spec.get("resolution") or "")
    if resolution:
        expected_width, expected_height = (int(value) for value in resolution.split("x"))
        if probe.get("width") != expected_width or probe.get("height") != expected_height:
            probe["errors"].append(
                f"resolution mismatch: expected {resolution}, got {probe.get('width')}x{probe.get('height')}"
            )
    expected_fps = int(spec.get("fps") or 0)
    if expected_fps:
        numerator, denominator = (int(value) for value in str(probe.get("fps") or "0/1").split("/"))
        actual_fps = numerator / max(denominator, 1)
        if abs(actual_fps - expected_fps) > 0.01:
            probe["errors"].append(f"fps mismatch: expected {expected_fps}, got {actual_fps:g}")
    return {**probe, "ok": not probe["errors"], "execution_node": "remote-gpu", "job_id": job_id}
'''
    if old in text:
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
    py_compile.compile(str(path), doraise=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup-dir", required=True, type=Path)
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    for item in args.paths:
        patch(item, args.backup_dir)
