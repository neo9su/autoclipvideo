"""Run with --db PATH. Database is opened read-only; never generates media."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from wig_identity import audit_database


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    args = parser.parse_args()
    print(json.dumps(audit_database(args.db), ensure_ascii=False, indent=2))
