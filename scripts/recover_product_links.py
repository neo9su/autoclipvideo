"""Safely replace synthetic catalogue placeholders with real link-bearing rows."""
import argparse
import datetime as dt
import json
import sqlite3
from pathlib import Path


ACTIVE = ("pending", "scheduled", "publishing")


def load_plan(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for candidate in data.get("candidates", []):
        for record in candidate.get("records", []):
            rows.append((candidate["catalogue_id"], record))
    return rows


def apply(db_path, manifest_path, journal_path, backup_path, dry_run=False):
    if journal_path.exists():
        raise RuntimeError(f"journal already exists: {journal_path}")
    source_rows = load_plan(manifest_path)
    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        columns = [x[1] for x in con.execute("PRAGMA table_info(products)")]
        originals = {}
        inserts = []
        for target_id, record in source_rows:
            row = con.execute("SELECT * FROM products WHERE id=?", (target_id,)).fetchone()
            if not row:
                raise RuntimeError(f"missing catalogue row {target_id}")
            row = dict(row)
            if row.get("product_url"):
                raise RuntimeError(f"catalogue row {target_id} already has a URL")
            if not str(row.get("product_id") or "").startswith("dom_"):
                raise RuntimeError(f"catalogue row {target_id} is not a synthetic placeholder")
            originals[target_id] = row
            pid, url = str(record["product_id"]), record["detail_url"]
            duplicate = con.execute(
                "SELECT id FROM products WHERE product_id=? OR product_url=?", (pid, url)
            ).fetchone()
            if duplicate:
                raise RuntimeError(f"real product already exists: {pid}/{url}")
            clone = {k: row.get(k) for k in columns if k != "id"}
            clone.update(product_id=pid, product_url=url, enabled=1)
            if "store_name" in clone:
                clone["store_name"] = record.get("shop_name") or clone.get("store_name")
            if "link_meta" in clone:
                try:
                    meta = json.loads(clone.get("link_meta") or "{}")
                except (ValueError, TypeError):
                    meta = {}
                if not isinstance(meta, dict):
                    meta = {}
                meta.update({"recovered_from_catalogue_id": target_id,
                             "recovery_source": "authenticated_buyin_shop_page"})
                clone["link_meta"] = json.dumps(meta, ensure_ascii=False)
            inserts.append(clone)
        target_ids = set(originals)
        active = con.execute(
            "SELECT id,status,product_id,product_ids FROM publish_tasks WHERE status IN (?,?,?)", ACTIVE
        ).fetchall()
        blocking = []
        for task in active:
            ids = {int(x) for x in str(task["product_ids"] or "").split(",") if x.strip().isdigit()}
            if task["product_id"] is not None:
                ids.add(int(task["product_id"]))
            if task["status"] == "publishing" or ids.intersection(target_ids):
                blocking.append(dict(task))
        if blocking:
            raise RuntimeError(f"affected active publish tasks: {blocking}")
        preview = {"mode": "dry_run" if dry_run else "apply",
                   "targets": sorted(originals), "insert_count": len(inserts)}
        if dry_run:
            return preview
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        if backup_path.exists():
            raise RuntimeError(f"backup already exists: {backup_path}")
        with sqlite3.connect(backup_path) as backup:
            con.backup(backup)
        inserted = []
        con.execute("BEGIN IMMEDIATE")
        try:
            for target_id in originals:
                cur = con.execute(
                    "UPDATE products SET enabled=0 WHERE id=? AND enabled=? AND coalesce(product_url,'')=''",
                    (target_id, originals[target_id].get("enabled")),
                )
                if cur.rowcount != 1:
                    raise RuntimeError(f"concurrent change detected for {target_id}")
            for clone in inserts:
                names = list(clone)
                cur = con.execute(
                    f"INSERT INTO products ({','.join(names)}) VALUES ({','.join('?' for _ in names)})",
                    [clone[n] for n in names],
                )
                inserted.append({"id": cur.lastrowid, "product_id": clone["product_id"],
                                 "product_url": clone["product_url"]})
            con.commit()
        except Exception:
            con.rollback()
            raise
        journal = {"created_at": dt.datetime.now().isoformat(), "database": str(db_path),
                   "backup": str(backup_path), "manifest": str(manifest_path),
                   "originals": list(originals.values()), "inserted": inserted}
        journal_path.write_text(json.dumps(journal, ensure_ascii=False, indent=2), encoding="utf-8")
        return {**preview, "inserted_ids": [x["id"] for x in inserted]}
    finally:
        con.close()


def rollback(db_path, journal_path):
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    con = sqlite3.connect(db_path, timeout=30)
    try:
        con.execute("BEGIN IMMEDIATE")
        for row in journal["inserted"]:
            cur = con.execute(
                "DELETE FROM products WHERE id=? AND product_id=? AND product_url=?",
                (row["id"], row["product_id"], row["product_url"]),
            )
            if cur.rowcount != 1:
                raise RuntimeError(f"inserted row changed or missing: {row['id']}")
        for row in journal["originals"]:
            cur = con.execute(
                "UPDATE products SET enabled=? WHERE id=? AND enabled=0 AND coalesce(product_url,'')=''",
                (row.get("enabled"), row["id"]),
            )
            if cur.rowcount != 1:
                raise RuntimeError(f"original row changed or missing: {row['id']}")
        con.commit()
        return {"rolled_back": len(journal["inserted"]),
                "restored_placeholders": len(journal["originals"])}
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("dry-run", "apply", "rollback"))
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    if args.mode == "rollback":
        result = rollback(args.db, args.journal)
    else:
        if not args.manifest or not args.backup:
            parser.error("--manifest and --backup are required")
        result = apply(args.db, args.manifest, args.journal, args.backup,
                       dry_run=args.mode == "dry-run")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
