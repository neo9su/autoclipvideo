#!/usr/bin/env python3
"""
修复导演模式和自编版视频缺失问题。

根因：1292+ 个分组 classic_status=2（经典版成功），但 director_status=-1 且 creative_status=-1。
这些分组在早期尝试触发导演/自编版管线时失败（时长不足导致 clipped=-1），
使得 _auto_merge_group 永远无法满足"所有 active recordings = clipped=2"的条件，
而 backfill_auto_merge 只重试 status=0 的分组，跳过 status=-1 的。

修复策略：
1. 找到所有 classic_status=2 + merged_filename IS NOT NULL + (director_status=-1 OR creative_status=-1) 的分组
2. 将这些分组的 director_status 和 creative_status 重置为 0
3. 异步触发 _run_director_pipeline 和 _run_creative_pipeline
4. 先处理少量分组验证，成功后再批量

用法：
  python3 scripts/fix_director_creative.py [--dry-run] [--batch N]
"""
import asyncio
import argparse
import logging
import os
import sys

# Add backend to path so we can import transcribe functions
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import aiosqlite
from transcribe import _run_director_pipeline, _run_creative_pipeline, aio_connect

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "douyin.db")


def parse_args():
    parser = argparse.ArgumentParser(description="Fix director/creative pipeline status for failed groups")
    parser.add_argument("--dry-run", action="store_true", help="Only show what would be done, don't execute")
    parser.add_argument("--batch", type=int, default=5, help="Number of groups to process in the first batch (default: 5)")
    parser.add_argument("--all", action="store_true", help="Process ALL matching groups (use with caution)")
    return parser.parse_args()


async def get_target_groups(db) -> list[dict]:
    """Find groups that need fixing."""
    async with db.execute("""
        SELECT id, merged_filename, label, wig_model, wig_color,
               director_status, creative_status,
               director_error
        FROM clip_groups
        WHERE classic_status = 2
          AND merged_filename IS NOT NULL
          AND (director_status = -1 OR creative_status = -1)
        ORDER BY id DESC
    """) as cur:
        return await cur.fetchall()


def group_recording_stats(db, group_id: int) -> dict:
    """Get recording clip breakdown for a group."""
    # We run this as a subprocess to avoid aiosqlite connection issues
    import subprocess
    result = subprocess.run(
        ["python3", "-c", f"""
import asyncio, aiosqlite
async def main():
    db = await aiosqlite.connect("douyin.db")
    db.row_factory = aiosqlite.Row
    async with db.execute("SELECT clipped, COUNT(*) as c FROM recordings WHERE group_id=? GROUP BY clipped", ({group_id},)) as cur:
        for r in await cur.fetchall():
            print(f"clipped={r['clipped']}: {r['c']}")
    async with db.execute("SELECT COUNT(*) as c FROM recordings WHERE group_id=?", ({group_id},)) as cur:
        row = await cur.fetchone()
        print(f"total: {row['c']}")
    await db.close()
asyncio.run(main())
"""],
        capture_output=True, text=True,
        cwd=os.path.dirname(DB_PATH),
    )
    return result.stdout.strip()


async def reset_status(db, group_id: int, pipeline: str):
    """Reset a pipeline's status from -1 to 0 and clear error."""
    await db.execute(
        f"UPDATE clip_groups SET {pipeline}_status = 0, {pipeline}_error = NULL WHERE id = ?",
        (group_id,),
    )


async def process_group(group_id: int, dry_run: bool = False):
    """Reset and trigger both pipelines for a single group."""
    logger.info(f"Processing group {group_id}...")

    if not dry_run:
        async with aio_connect() as db:
            await reset_status(db, group_id, "director")
            await reset_status(db, group_id, "creative")
            await db.commit()
        logger.info(f"  ✓ Reset director_status and creative_status to 0 for group {group_id}")

    if dry_run:
        logger.info(f"  [DRY RUN] Would trigger director + creative pipelines for group {group_id}")
    else:
        # Trigger pipelines in background (they run independently)
        asyncio.create_task(_run_director_pipeline(group_id))
        asyncio.create_task(_run_creative_pipeline(group_id))
        logger.info(f"  ✓ Queued director + creative pipelines for group {group_id}")


async def main():
    args = parse_args()

    logger.info("=" * 60)
    logger.info("Fix Director/Creative Pipeline Status")
    logger.info("=" * 60)

    async with aio_connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        groups = await get_target_groups(db)

    logger.info(f"Found {len(groups)} groups matching criteria:")
    logger.info("  classic_status=2 + merged_filename IS NOT NULL + (director_status=-1 OR creative_status=-1)")

    # Show breakdown
    both_failed = [g for g in groups if g["director_status"] == -1 and g["creative_status"] == -1]
    director_failed_only = [g for g in groups if g["director_status"] == -1 and g["creative_status"] != -1]
    creative_failed_only = [g for g in groups if g["director_status"] != -1 and g["creative_status"] == -1]

    logger.info(f"  Both director & creative failed: {len(both_failed)}")
    logger.info(f"  Director only failed:            {len(director_failed_only)}")
    logger.info(f"  Creative only failed:            {len(creative_failed_only)}")

    if not groups:
        logger.info("No groups to fix. Done!")
        return

    if args.dry_run:
        logger.info("DRY RUN mode — no changes will be made")
        dry_count = min(args.batch, len(groups))
        logger.info(f"\nWould process {dry_count} group(s) (out of {len(groups)} total).")
        logger.info("Groups (first 10):")
        for g in groups[:10]:
            logger.info(f"  group {g['id']}: {g['label']} (director={g['director_status']}, creative={g['creative_status']})")
        return

    # Determine how many to process
    if args.all:
        count = len(groups)
    else:
        count = min(args.batch, len(groups))

    targets = groups[:count]

    logger.info(f"Processing {count} group(s): {[g['id'] for g in targets]}")
    logger.info("Each group will:")
    logger.info("  1. Reset director_status & creative_status from -1 to 0")
    logger.info("  2. Trigger _run_director_pipeline (async)")
    logger.info("  3. Trigger _run_creative_pipeline (async)")
    logger.info("Pipelines run independently; check status with:")
    logger.info("  SELECT id, classic_status, director_status, creative_status FROM clip_groups WHERE id IN (...)")

    # Process all targets
    for g in targets:
        await process_group(g["id"], dry_run=False)
        await asyncio.sleep(0.3)  # stagger slightly

    # Summary
    logger.info("=" * 60)
    logger.info(f"Done! Processed {count} group(s).")
    if not args.all:
        remaining = len(groups) - count
        if remaining > 0:
            logger.info(f"Remaining: {remaining} group(s). Run with --all to process all.")
    logger.info("Verify with:")
    logger.info("  SELECT director_status, creative_status, COUNT(*) as c")
    logger.info("  FROM clip_groups WHERE classic_status=2")
    logger.info("  GROUP BY director_status, creative_status;")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
