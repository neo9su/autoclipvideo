"""Scoped review-hold rollback. Default is dry-run; --apply requires a new backup.

Never restore the entire database to roll back a handful of review statuses.
"""
import argparse
import json
from pathlib import Path
import sqlite3


def rollback_holds(db_path, group_ids, version="qianchuan", apply=False, backup=None):
    if version not in {"qianchuan", "qianchuan_v2"} or not group_ids:
        raise ValueError("Choose a supported version and explicit group IDs")
    ids = sorted(set(int(i) for i in group_ids))
    columns = [f"{version}_{field}" for field in ("status", "error", "review")]
    mode = "rw" if apply else "ro"
    with sqlite3.connect(Path(db_path).resolve().as_uri() + f"?mode={mode}", uri=True, timeout=30) as db:
        planned = []
        for gid in ids:
            row = db.execute(f"SELECT {','.join(columns)} FROM clip_groups WHERE id=?", (gid,)).fetchone()
            if not row or row[0] != -5:
                raise ValueError(f"Not an active review hold: {gid}")
            saved = json.loads(row[2] or "{}")
            previous = saved.get("previous_state") or {}
            if saved.get("hold_type") != "wig_identity_v1" or "status" not in previous:
                raise ValueError(f"Hold is not owned by this release: {gid}")
            # An interrupted task cannot be resumed by restoring its running flag.
            status = 0 if previous["status"] in (None, 1) else previous["status"]
            if status not in {0, 2, -1, -2, -3, -4}:
                raise ValueError(f"Unsupported previous status: {gid}")
            planned.append((gid, row[2], status, previous.get("error"), previous.get("review")))
        if apply:
            if not backup:
                raise ValueError("Apply requires a new SQLite backup path")
            dest = Path(backup).resolve()
            if dest == Path(db_path).resolve():
                raise ValueError("Backup cannot be the live database")
            with dest.open("xb"):
                pass
            with sqlite3.connect(dest) as snapshot:
                db.backup(snapshot)
            db.execute("BEGIN IMMEDIATE")
            for gid, saved, status, error, review in planned:
                changed = db.execute(
                    f"UPDATE clip_groups SET {columns[0]}=?, {columns[1]}=?, {columns[2]}=? "
                    f"WHERE id=? AND {columns[0]}=-5 AND {columns[2]} IS ?",
                    (status, error, review, gid, saved),
                ).rowcount
                if changed != 1:
                    raise ValueError(f"Hold changed since planning: {gid}")
            db.commit()
    return {"applied": apply, "version": version,
            "groups": [{"id": r[0], "restore_status": r[2]} for r in planned]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--group-id", required=True, action="append", type=int)
    parser.add_argument("--version", default="qianchuan", choices=["qianchuan", "qianchuan_v2"])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup")
    args = parser.parse_args()
    print(json.dumps(rollback_holds(args.db, args.group_id, args.version, args.apply, args.backup)))
