#!/usr/bin/env python3
"""
批量发布任务排期脚本
策略：
  - 3个账号（id=2/4/5）轮流，共享分组池，合计每小时3条
  - 账号2（颜遇生活）：每小时 :00 分
  - 账号4（可利）    ：每小时 :20 分（错开20分钟）
  - 账号5（星云阁百货）：每小时 :40 分（错开40分钟）
  - 不挂车 no_cart=True
  - 从最早的分组开始排期（全局共享池，轮流派发）
  - 0-7 点不发（顺移到 08:xx）

用法：
  python3 scripts/schedule_publish.py [--days 1] [--start "2026-06-03T18:00:00"]
"""
import argparse
import asyncio
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

import aiosqlite

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'douyin.db')

ACCOUNTS = [
    {"id": 2, "name": "颜遇生活",   "offset_min": 0},
    {"id": 4, "name": "可利",       "offset_min": 20},
    {"id": 5, "name": "星云阁百货", "offset_min": 40},
]

RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), '..', 'recordings')


async def get_all_pending_groups() -> list:
    """获取所有还没有 scheduled/pending/done 任务的分组，按 id ASC 排序。"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT g.id, g.room_id, g.merged_filename, g.wig_model, g.wig_color
            FROM clip_groups g
            WHERE g.classic_status = 2
              AND g.merged_filename IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM publish_tasks pt
                  WHERE pt.group_id = g.id
                    AND pt.platform = 'douyin'
                    AND pt.status IN ('pending', 'scheduled', 'publishing', 'done')
              )
            ORDER BY g.id ASC
        """) as cur:
            rows = await cur.fetchall()

    valid = []
    for r in rows:
        path = os.path.join(RECORDINGS_DIR, r[2])
        if os.path.exists(path):
            valid.append(dict(zip(['id', 'room_id', 'merged_filename', 'wig_model', 'wig_color'], r)))
    return valid


async def create_task(db, group_id: int, account_id: int, scheduled_at: str):
    """直接向 DB 插入发布任务。"""
    # 查视频路径
    async with db.execute("SELECT merged_filename FROM clip_groups WHERE id=?", (group_id,)) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    video_path = os.path.join(RECORDINGS_DIR, row[0])

    # 检查重复
    async with db.execute(
        "SELECT id FROM publish_tasks WHERE group_id=? AND platform='douyin' AND status IN ('pending','scheduled','publishing','done') LIMIT 1",
        (group_id,)
    ) as cur:
        if await cur.fetchone():
            return None

    async with db.execute("""
        INSERT INTO publish_tasks
          (group_id, platform, account_id, status, scheduled_at, video_path, no_cart, created_at)
        VALUES (?, 'douyin', ?, 'scheduled', ?, ?, 1, datetime('now'))
    """, (group_id, account_id, scheduled_at, video_path)) as cur:
        task_id = cur.lastrowid
    await db.commit()
    return task_id


async def main(start_dt: datetime, days: int):
    print(f"开始排期：从 {start_dt.isoformat()} 起，共 {days} 天")
    print(f"策略：三账号轮流，每小时各1条（合计每小时3条），凌晨0-7点不发，不挂车")
    print()

    all_groups = await get_all_pending_groups()
    print(f"待发布分组总数（视频文件存在）: {len(all_groups)} 个")
    print()

    group_iter = iter(all_groups)
    done = False

    total_created = 0
    created_by_acct = {a["id"]: 0 for a in ACCOUNTS}

    async with aiosqlite.connect(DB_PATH) as db:
        end_dt = start_dt + timedelta(days=days)
        current_hour = start_dt.replace(minute=0, second=0, microsecond=0)

        while current_hour < end_dt and not done:
            # 跳过凌晨 0-7 点
            if 0 <= current_hour.hour < 8:
                current_hour += timedelta(hours=1)
                continue

            for acct in ACCOUNTS:
                try:
                    group = next(group_iter)
                except StopIteration:
                    print("所有分组已排完！")
                    done = True
                    break

                sched_dt = current_hour + timedelta(minutes=acct["offset_min"])
                scheduled_at = sched_dt.strftime("%Y-%m-%dT%H:%M:%S")
                task_id = await create_task(db, group["id"], acct["id"], scheduled_at)
                if task_id:
                    total_created += 1
                    created_by_acct[acct["id"]] += 1
                    model = group.get("wig_model") or "未知款"
                    color = group.get("wig_color") or "未知色"
                    print(f"  [{scheduled_at}] 账号{acct['id']} {acct['name']} → group={group['id']} {model} {color}")

            current_hour += timedelta(hours=1)

    print()
    print(f"✅ 共创建 {total_created} 条发布任务")
    for acct in ACCOUNTS:
        print(f"  账号{acct['id']} {acct['name']}：{created_by_acct[acct['id']]} 条")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=1, help="排期天数（默认1天）")
    parser.add_argument("--start", type=str, default=None, help="起始时间 ISO格式，默认下一整点")
    args = parser.parse_args()

    if args.start:
        start = datetime.fromisoformat(args.start)
    else:
        now = datetime.now()
        start = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

    asyncio.run(main(start, args.days))
