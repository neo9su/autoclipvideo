"""Review endpoints: inspect evidence, then explicitly recheck repaired metadata."""
from fastapi import APIRouter, HTTPException

from wig_identity_review import REVIEW_REQUIRED, VERSIONS, hold_for_review, release_after_recheck

identity_router = APIRouter()


async def _context(group_id, version):
    from db import DB_PATH
    from qianchuan_matcher import load_group_context
    if version not in VERSIONS:
        raise HTTPException(status_code=422, detail="不支持的千川版本")
    context = await load_group_context(DB_PATH, group_id)
    if not context:
        raise HTTPException(status_code=404, detail="分组不存在")
    if version + "_status" not in context["group"]:
        raise HTTPException(status_code=409, detail="该版本尚未启用")
    return context


@identity_router.get("/group/{group_id}/identity-review")
async def get_identity_review(group_id: int, version: str = "qianchuan"):
    context = await _context(group_id, version)
    return {"group_id": group_id, "version": version,
            "status": context["group"].get(version + "_status"),
            "identity": context.get("identity"), "read_only": True}


@identity_router.post("/group/{group_id}/identity-recheck")
async def recheck_identity(group_id: int, version: str = "qianchuan"):
    from db import aio_connect
    context = await _context(group_id, version)
    identity = context.get("identity")
    try:
        async with aio_connect() as db:
            held = await hold_for_review(db, group_id, identity, version)
            status = REVIEW_REQUIRED if held else await release_after_recheck(db, group_id, identity, version)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"group_id": group_id, "version": version, "success": not held,
            "status": status, "identity": identity, "review_required": held,
            "visual_verified": False, "started": False}
