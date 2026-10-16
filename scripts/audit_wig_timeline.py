"""Read-only SRT timeline audit for explicitly selected recording IDs (max 20)."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from wig_timeline import analyze_timeline


def find_srt(filename, room_id, roots):
    for root in map(Path, roots):
        for base in [root, root / str(room_id)]:
            for candidate in [(base / filename).with_suffix(".srt"), base / (filename + ".srt")]:
                try:
                    if candidate.is_file() and 0 < candidate.stat().st_size <= 10 * 1024 * 1024:
                        return candidate
                except OSError:
                    pass
    return None


def audit_recordings(db_path, recording_ids, roots, target_key=None):
    ids = list(dict.fromkeys(recording_ids))
    if not ids or len(ids) > 20:
        raise ValueError("Select between 1 and 20 explicit recording IDs")
    reports = []
    with sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        cols = {r[1] for r in db.execute("PRAGMA table_info(products)")}
        if not {"id", "short_name", "room_id", "enabled"}.issubset(cols):
            raise ValueError("Catalog short-name/room metadata unavailable; review catalog first")
        for rid in ids:
            rec = db.execute("SELECT id,filename,room_id FROM recordings WHERE id=?", (rid,)).fetchone()
            if rec is None:
                reports.append({"recording_id": rid, "error": "recording_not_found"})
                continue
            catalog = [{"key": f"catalog:{p['id']}", "aliases": [p["short_name"]]}
                       for p in db.execute("SELECT id,short_name FROM products WHERE enabled=1 AND (room_id IS NULL OR room_id=?) AND short_name IS NOT NULL AND length(short_name)>1 ORDER BY id", (rec["room_id"],))]
            srt = find_srt(rec["filename"], rec["room_id"], roots)
            if srt is None:
                reports.append({"recording_id": rid, "error": "srt_missing_unreadable_or_over_limit"})
                continue
            try:
                raw = srt.read_bytes()
                text = raw.decode("utf-8-sig")
            except (OSError, UnicodeError):
                reports.append({"recording_id": rid, "error": "srt_read_or_encoding_error"})
                continue
            report = analyze_timeline(text, catalog, rid, target_key)
            report["srt_file_sha256"] = hashlib.sha256(raw).hexdigest()
            report["srt_filename"] = srt.name
            reports.append(report)
    return {"version": "wig-transcript-timeline-v1", "read_only": True, "reports": reports}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--recording-id", required=True, type=int, action="append")
    parser.add_argument("--storage-root", required=True, action="append")
    parser.add_argument("--target-key")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = audit_recordings(args.db, args.recording_id, args.storage_root, args.target_key)
    with Path(args.output).open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({"read_only": True, "recordings": len(result["reports"])}))
