"""Persistent review holds. -5 is deliberately outside automatic retry states."""
import json

REVIEW_REQUIRED = -5
VERSIONS = {"qianchuan", "qianchuan_v2"}
_MESSAGES = {
    "ambiguous_group_identity": "分组款式或颜色不明确",
    "multiple_group_products": "分组包含多个商品简称",
    "no_recording_evidence": "没有已转录的候选录像",
    "missing_room": "房间证据缺失",
    "room_mismatch": "录像与分组房间不同",
    "missing_recording_identity": "录像缺少款式或颜色",
    "recording_identity_conflict": "录像与目标款式或颜色冲突",
    "multiple_products_in_recording": "录像提及多个商品",
    "product_name_conflict": "录像与目标商品简称冲突",
    "different_recording_products": "候选录像对应不同商品",
}


def review_message(identity):
    issues = (identity or {}).get("issues") or []
    reasons = list(dict.fromkeys(_MESSAGES.get(i.get("code"), "需核实款式证据") for i in issues))
    return "款式一致性待审核：" + ("；".join(reasons[:3]) or "缺少一致性证据")


def _columns(version):
    if version not in VERSIONS:
        raise ValueError("Unsupported Qianchuan version")
    return tuple(f"{version}_{name}" for name in ("status", "error", "review"))


async def hold_for_review(db, group_id, identity, version="qianchuan"):
    """Persist failed identity evidence; keep the pre-hold state for rollback.

    Callers must return before script/TTS/render execution when this returns True.
    Repeating the hold never nests or overwrites the original state snapshot.
    """
    if identity and identity.get("ok"):
        return False
    status_col, error_col, review_col = _columns(version)
    async with db.execute(
        f"SELECT {status_col}, {error_col}, {review_col} FROM clip_groups WHERE id=?", (group_id,)
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        raise ValueError("Group not found")
    previous = {"status": row[0], "error": row[1], "review": row[2]}
    if row[0] == REVIEW_REQUIRED:
        try:
            old = json.loads(row[2] or "{}")
            if old.get("hold_type") == "wig_identity_v1" and isinstance(old.get("previous_state"), dict):
                previous = old["previous_state"]
        except (ValueError, AttributeError):
            pass
    payload = {"hold_type": "wig_identity_v1", "identity": identity,
               "previous_state": previous, "visual_verified": False}
    async with db.execute(
        f"UPDATE clip_groups SET {status_col}=?, {error_col}=?, {review_col}=? "
        f"WHERE id=? AND {status_col} IS ? AND {review_col} IS ?",
        (REVIEW_REQUIRED, review_message(identity), json.dumps(payload, ensure_ascii=False), group_id, row[0], row[2]),
    ) as cur:
        changed = cur.rowcount
    if changed != 1:
        raise RuntimeError("Group changed during identity check; retry read-only review")
    await db.commit()
    return True


async def release_after_recheck(db, group_id, identity, version="qianchuan"):
    """Explicit recheck only: never treat a click as approval of conflicting data."""
    if not identity or not identity.get("ok"):
        raise ValueError("Identity evidence is still missing or conflicting")
    status_col, error_col, review_col = _columns(version)
    async with db.execute(
        f"SELECT {status_col}, {review_col} FROM clip_groups WHERE id=?", (group_id,)
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        raise ValueError("Group not found")
    if row[0] != REVIEW_REQUIRED:
        return row[0]
    old = json.loads(row[1] or "{}")
    if old.get("hold_type") != "wig_identity_v1":
        raise ValueError("Review hold is not owned by this policy")
    previous = old.get("previous_state") or {}
    # Preserve an already completed artifact; interrupted runs must be reclaimed.
    next_status = 2 if previous.get("status") == 2 else 0
    payload = {"identity": identity, "rechecked": True, "visual_verified": False}
    async with db.execute(
        f"UPDATE clip_groups SET {status_col}=?, {error_col}=NULL, {review_col}=? "
        f"WHERE id=? AND {status_col}=? AND {review_col} IS ?",
        (next_status, json.dumps(payload, ensure_ascii=False), group_id, REVIEW_REQUIRED, row[1]),
    ) as cur:
        changed = cur.rowcount
    if changed != 1:
        raise RuntimeError("Group changed during recheck")
    await db.commit()
    return next_status
