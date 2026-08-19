"""Atomic, idempotent pipeline claims."""
from __future__ import annotations

_ALLOWED = {"director_status", "qianchuan_status"}

# ``-2`` is normally terminal (for example, product-match rejection).  A
# missing-media preflight is different: after an operator restores the source
# to storage, the same Qianchuan request can be retried without touching any
# completed pipeline.  Keep this allow-list narrow so other terminal failures
# remain terminal.
_MISSING_MEDIA_MARKERS = (
    "missing-media",
    "sync_mp4_to_storage",
    "media_unavailable",
    "source media/srt unavailable",
    "no usable source media/srt",
)


def is_qianchuan_missing_media_error(error: object) -> bool:
    """Return whether an error is the explicitly recoverable media preflight."""
    message = str(error or "").strip().lower()
    return bool(message) and any(marker in message for marker in _MISSING_MEDIA_MARKERS)


async def claim_pipeline_start(
    db,
    status_column: str,
    group_id: int,
    *,
    allow_missing_media_retry: bool = False,
) -> bool:
    """Transition a pending/retryable pipeline to running exactly once.

    Qianchuan ``-2`` remains terminal unless its stored error identifies the
    narrow missing-media preflight.  This supports an idempotent retry after
    ``sync_mp4_to_storage`` while leaving product-match and other ``-2``
    failures untouched.
    """
    if status_column not in _ALLOWED:
        raise ValueError(f"unsupported pipeline: {status_column}")
    retry_condition = f"{status_column} IN (0,-1,-3,-4)"
    params: tuple[object, ...] = (group_id,)
    if status_column == "qianchuan_status" and allow_missing_media_retry:
        retry_condition += (
            " OR (qianchuan_status = -2 AND "
            "(lower(COALESCE(qianchuan_error, '')) LIKE '%missing-media%' OR "
            "lower(COALESCE(qianchuan_error, '')) LIKE '%sync_mp4_to_storage%' OR "
            "lower(COALESCE(qianchuan_error, '')) LIKE '%media_unavailable%' OR "
            "lower(COALESCE(qianchuan_error, '')) LIKE '%source media/srt unavailable%' OR "
            "lower(COALESCE(qianchuan_error, '')) LIKE '%no usable source media/srt%'))"
        )
    cursor = await db.execute(
        f"UPDATE clip_groups SET {status_column}=1 WHERE id=? AND ({retry_condition})",
        params,
    )
    return cursor.rowcount == 1
