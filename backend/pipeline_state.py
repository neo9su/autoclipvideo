"""Atomic, idempotent pipeline claims."""
from __future__ import annotations

_ALLOWED = {"director_status", "qianchuan_status"}

async def claim_pipeline_start(db, status_column: str, group_id: int) -> bool:
    """Transition a pending/retryable pipeline to running exactly once."""
    if status_column not in _ALLOWED:
        raise ValueError(f"unsupported pipeline: {status_column}")
    cursor = await db.execute(
        f"UPDATE clip_groups SET {status_column}=1 WHERE id=? AND {status_column} IN (0,-1,-3,-4)",
        (group_id,),
    )
    return cursor.rowcount == 1
