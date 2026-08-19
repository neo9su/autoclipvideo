import aiosqlite
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from backend.api_v2 import _build_qianchuan_script_segments
from backend.pipeline_state import claim_pipeline_start


@pytest.mark.asyncio
async def test_missing_media_qianchuan_failure_can_be_reclaimed_after_sync() -> None:
    """Only the explicit missing-media preflight may reopen terminal -2."""
    async with aiosqlite.connect(":memory:") as db:
        await db.execute(
            "CREATE TABLE clip_groups (id INTEGER PRIMARY KEY, qianchuan_status INTEGER, qianchuan_error TEXT)"
        )
        await db.executemany(
            "INSERT INTO clip_groups VALUES (?, ?, ?)",
            [
                (4675, -2, "missing-media preflight: sync_mp4_to_storage required"),
                (4685, -2, "商品强匹配不足"),
            ],
        )
        assert await claim_pipeline_start(
            db, "qianchuan_status", 4675, allow_missing_media_retry=True
        )
        assert not await claim_pipeline_start(
            db, "qianchuan_status", 4685, allow_missing_media_retry=True
        )
        rows = await db.execute_fetchall(
            "SELECT id, qianchuan_status FROM clip_groups ORDER BY id"
        )
        assert rows == [(4675, 1), (4685, -2)]


@pytest.mark.asyncio
async def test_qianchuan_claim_remains_idempotent_for_running_group() -> None:
    async with aiosqlite.connect(":memory:") as db:
        await db.execute(
            "CREATE TABLE clip_groups (id INTEGER PRIMARY KEY, qianchuan_status INTEGER, qianchuan_error TEXT)"
        )
        await db.execute("INSERT INTO clip_groups VALUES (1, 0, NULL)")
        assert await claim_pipeline_start(db, "qianchuan_status", 1)
        assert not await claim_pipeline_start(db, "qianchuan_status", 1)



@pytest.mark.parametrize("scene_type", ["result_hook", "product_proof", "cta"])
def test_qianchuan_background_segments_keep_scene_type(scene_type: str) -> None:
    """Background generation must pass each scene type into the matcher/composer."""
    script = {
        "scenes": [
            {
                "scene_id": 4,
                "scene_type": scene_type,
                "voiceover_text": "展示发型效果",
                "visual_requirements": ["自然"],
                "duration": 3.0,
            }
        ]
    }

    segments = _build_qianchuan_script_segments(
        script, [{"scene_id": 4, "duration": 4.25}]
    )

    assert segments == [
        {
            "text": "展示发型效果",
            "voiceover_text": "展示发型效果",
            "visual_keywords": ["自然"],
            "priority_shots": [],
            "duration": 4.25,
            "scene_type": scene_type,
            "scene_id": 4,
        }
    ]
