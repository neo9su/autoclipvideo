#!/usr/bin/env python3
"""
批量触发 director_status=0 的分组，每批50个。
由 OpenClaw cron 每5分钟调用，直到队列清空。
"""
import sqlite3, requests, time, sys, json
from datetime import datetime

DB = "/Users/claw/work/douyin-recorder/douyin.db"
API = "http://localhost:8899"
BATCH = 50

def main():
    conn = sqlite3.connect(DB)
    rows = conn.execute('''
        SELECT id FROM clip_groups
        WHERE director_status = 0
          AND merge_status = 2
          AND editing_mode = 'director'
        ORDER BY id ASC
        LIMIT ?
    ''', (BATCH,)).fetchall()
    ids = [r[0] for r in rows]
    conn.close()

    if not ids:
        print(f"[{datetime.now():%H:%M:%S}] 全部触发完毕，无剩余任务")
        # 写标记文件让 cron 知道可以停了
        with open("/tmp/director_batch_done", "w") as f:
            f.write("done")
        return

    # 统计剩余总数
    conn2 = sqlite3.connect(DB)
    total_left = conn2.execute('''
        SELECT COUNT(*) FROM clip_groups
        WHERE director_status = 0 AND merge_status = 2 AND editing_mode = 'director'
    ''').fetchone()[0]
    conn2.close()

    print(f"[{datetime.now():%H:%M:%S}] 触发批次: {len(ids)}个 (id={ids[0]}~{ids[-1]})，剩余总计={total_left}个")

    ok, fail = 0, []
    for gid in ids:
        try:
            r = requests.post(
                f"{API}/api/groups/{gid}/retry-modes",
                json={"retry_director": True, "retry_creative": False, "retry_classic": False},
                timeout=5
            )
            if r.status_code in (200, 201):
                ok += 1
            else:
                fail.append((gid, r.status_code))
        except Exception as e:
            fail.append((gid, str(e)))
        time.sleep(0.05)

    print(f"  成功={ok} 失败={len(fail)}")
    if fail:
        print(f"  失败: {fail[:5]}")

    # 还有多少剩余
    conn3 = sqlite3.connect(DB)
    remaining = conn3.execute('''
        SELECT COUNT(*) FROM clip_groups
        WHERE director_status = 0 AND merge_status = 2 AND editing_mode = 'director'
    ''').fetchone()[0]
    conn3.close()
    print(f"  触发后剩余待触发: {remaining}个")

    if remaining == 0:
        with open("/tmp/director_batch_done", "w") as f:
            f.write("done")
        print("  ✅ 全部触发完毕")

if __name__ == "__main__":
    main()
