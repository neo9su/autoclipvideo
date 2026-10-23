"""Conservative metadata gate. This does not certify visual or SKU identity."""

import re
import unicodedata
from collections import Counter
from pathlib import Path
import sqlite3

POLICY_VERSION = "wig-identity-v1"
_UNKNOWN = {"", "unknown", "none", "null", "未分类", "未知", "未知款", "未知色", "不确定"}


def _values(value):
    if isinstance(value, (list, tuple)):
        return set().union(*(_values(item) for item in value)) if value else set()
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    parts = re.split(r"[,，、;；|/]", text)
    return {re.sub(r"\s+", "", part) for part in parts
            if re.sub(r"\s+", "", part) not in _UNKNOWN}


def evaluate_identity(group, recordings):
    """Check ALL candidate recordings, independent of semantic score/threshold.

    Aliases are deliberately not guessed. Missing metadata requires review;
    explicit disagreement blocks generation. No text-only pass certifies pixels.
    """
    issues = []
    conflicts = 0
    targets = {field: _values(group.get(field)) for field in ("wig_model", "wig_color")}

    def issue(code, recording_id=None, field=None, expected=None, observed=None, conflict=False):
        nonlocal conflicts
        conflicts += int(conflict)
        issues.append({"code": code, "recording_id": recording_id, "field": field,
                       "expected": sorted(expected or []), "observed": sorted(observed or [])})

    for field, values in targets.items():
        if len(values) != 1:
            issue("ambiguous_group_identity", field=field, observed=values, conflict=len(values) > 1)
    products = _values(group.get("product_keywords"))
    if len(products) > 1:
        issue("multiple_group_products", field="product_keywords", observed=products)
    if not recordings:
        issue("no_recording_evidence")
    seen_products = set()
    for rec in recordings:
        rid = rec.get("id")
        if group.get("room_id") is None or rec.get("room_id") is None:
            issue("missing_room", rid)
        elif str(rec["room_id"]) != str(group["room_id"]):
            issue("room_mismatch", rid, conflict=True)
        for field, target in targets.items():
            values = _values(rec.get(field))
            if not values:
                issue("missing_recording_identity", rid, field)
            elif len(values) > 1 or (len(target) == 1 and values != target):
                issue("recording_identity_conflict", rid, field, target, values, conflict=True)
        hits = _values(rec.get("product_hits"))
        if len(hits) > 1:
            issue("multiple_products_in_recording", rid, "product_hits", observed=hits)
        if len(hits) == 1:
            seen_products.update(hits)
            if len(products) == 1 and hits != products:
                issue("product_name_conflict", rid, "product_hits", products, hits, conflict=True)
    if len(seen_products) > 1:
        issue("different_recording_products", field="product_hits", observed=seen_products, conflict=True)
    status = "conflict" if conflicts else "review_required" if issues else "metadata_consistent"
    return {"policy_version": POLICY_VERSION, "ok": not issues, "status": status,
            "recordings_checked": len(recordings), "issue_count": len(issues), "issues": issues[:50],
            "evidence_type": "recording_metadata", "visual_verified": False,
            "sku_verified": False, "requires_visual_review": True}


async def load_identity_evidence(db, group):
    """Read the complete transcribed candidate pool; never sample only five rows."""
    async with db.execute("PRAGMA table_info(recordings)") as cur:
        columns = {row[1] for row in await cur.fetchall()}
    fields = ("id", "room_id", "wig_model", "wig_color", "product_hits")
    projection = ", ".join(field if field in columns else f"NULL AS {field}" for field in fields)
    async with db.execute(
        f"SELECT {projection} FROM recordings WHERE group_id = ? AND transcribed = 2 ORDER BY id",
        (group["id"],),
    ) as cur:
        rows = await cur.fetchall()
    return evaluate_identity(dict(group), [dict(zip(fields, row)) for row in rows])


def audit_database(db_path):
    """Read-only rollout report; no model calls, media probes, writes or retries."""
    with sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        columns = {row[1] for row in db.execute("PRAGMA table_info(recordings)")}
        fields = ("id", "room_id", "wig_model", "wig_color", "product_hits")
        projection = ", ".join(field if field in columns else f"NULL AS {field}" for field in fields)
        counts, reasons, samples = Counter(), Counter(), []
        for row in db.execute("SELECT * FROM clip_groups ORDER BY id"):
            group = dict(row)
            recs = [dict(rec) for rec in db.execute(
                f"SELECT {projection} FROM recordings WHERE group_id=? AND transcribed=2 ORDER BY id",
                (group["id"],))]
            result = evaluate_identity(group, recs)
            counts[result["status"]] += 1
            reasons.update(issue["code"] for issue in result["issues"])
            if not result["ok"] and len(samples) < 20:
                samples.append({"group_id": group["id"], "status": result["status"],
                                "issue_count": result["issue_count"]})
        return {"policy_version": POLICY_VERSION, "read_only": True,
                "groups": sum(counts.values()), "statuses": dict(counts),
                "sample_issue_counts": dict(reasons), "sample_groups": samples,
                "scope": "transcribed_recording_metadata_not_visual_or_sku_verification"}
