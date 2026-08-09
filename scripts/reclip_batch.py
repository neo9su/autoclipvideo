#!/usr/bin/env python3
"""Build/resume an auditable reclip manifest without touching source media.

The default is planning only. Execution is deliberately opt-in and requires a
separate adapter that can provide validated GPU job evidence; queue state alone
never marks an item complete.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))
from reclip_batch import Manifest, discover_candidates


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create/resume a safe remote-GPU reclip manifest")
    parser.add_argument("--input", type=Path, required=True, help="read-only directory containing MP4/SRT pairs")
    parser.add_argument("--output", type=Path, required=True, help="isolated output directory")
    parser.add_argument("--manifest", type=Path, required=True, help="SQLite checkpoint path")
    parser.add_argument("--max-items", type=int, default=0, help="plan at most N candidates (0 means all)")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--lease-seconds", type=int, default=1800)
    parser.add_argument("--plan-only", action="store_true", default=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.input.is_dir():
        print(json.dumps({"status": "blocked", "reason": "input directory does not exist"}, ensure_ascii=False))
        return 2
    if args.input.resolve() == args.output.resolve() or args.output.resolve().is_relative_to(args.input.resolve()):
        print(json.dumps({"status": "blocked", "reason": "output must be isolated from input"}, ensure_ascii=False))
        return 2
    candidates = discover_candidates(args.input)
    if args.max_items > 0:
        candidates = candidates[: args.max_items]
    manifest = Manifest(args.manifest)
    try:
        imported = manifest.import_candidates(candidates)
        print(json.dumps({
            "status": "planned", "candidates": len(candidates), "imported": imported,
            "counts": manifest.counts(), "output_root": str(args.output.resolve()),
            "source_immutable": True, "execution": "not_started",
            "next_step": "Run a separately reviewed GPU adapter for a small proof batch; this command never submits jobs.",
        }, ensure_ascii=False, sort_keys=True))
    finally:
        manifest.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
