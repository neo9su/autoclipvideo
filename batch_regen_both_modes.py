#!/usr/bin/env python3
"""
批量重新剪辑最近50个分组 — 导演模式 + 经典模式双版本
用法：python batch_regen_both_modes.py [--dry-run] [--force-all]

  --dry-run    只打印将要执行的操作，不实际修改DB或调API
  --force-all  强制重置所有分组（含已完成），默认只重跑失败/待处理的
"""

import sqlite3
import time
import sys
import urllib.request
import json

DB_PATH = "/Users/claw/work/douyin-recorder/douyin.db"
API_BASE = "http://localhost:8899"
LIMIT = 50
DELAY_BETWEEN_CALLS = 1.0   # 每次调用间隔（秒），避免瞬间触发过多任务

STATUS_LABEL = {2: "✅done", 1: "⏳running", 0: "⬜pending", -1: "❌failed"}

dry_run = "--dry-run" in sys.argv
force_all = "--force-all" in sys.argv


def http_post(url: str) -> dict:
    req = urllib.request.Request(url, method="POST", data=b"",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}


def main():
    # 1. 读取最近50个分组
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """SELECT id, label, director_status, classic_status
           FROM clip_groups ORDER BY id DESC LIMIT ?""",
        (LIMIT,)
    ).fetchall()

    total = len(rows)
    print(f"\n📋 最近 {total} 个分组状态汇总")
    print(f"   导演版：{sum(1 for r in rows if r['director_status']==2)} 完成 / "
          f"{sum(1 for r in rows if r['director_status']==-1)} 失败 / "
          f"{sum(1 for r in rows if r['director_status']==0)} 待处理 / "
          f"{sum(1 for r in rows if r['director_status']==1)} 运行中")
    print(f"   经典版：{sum(1 for r in rows if r['classic_status']==2)} 完成 / "
          f"{sum(1 for r in rows if r['classic_status']==-1)} 失败 / "
          f"{sum(1 for r in rows if r['classic_status']==0)} 待处理 / "
          f"{sum(1 for r in rows if r['classic_status']==1)} 运行中\n")

    if force_all:
        print("⚠️  --force-all：强制重置所有分组（含已完成）\n")
        targets = list(rows)
    else:
        # 只处理至少一个版本不完整的分组
        targets = [r for r in rows if r['director_status'] != 2 or r['classic_status'] != 2]
        already_done = total - len(targets)
        print(f"ℹ️  已有两个版本完成的分组（跳过）：{already_done} 个")
        print(f"   需要补全的分组：{len(targets)} 个")
        if not targets:
            print("✅ 所有分组都已完成双版本，无需重跑。如需强制重跑请加 --force-all\n")
            con.close()
            return
        print()

    # 2. 在DB中重置状态（允许trigger_merge重新触发）
    ids = [r['id'] for r in targets]

    if force_all:
        reset_sql = """
            UPDATE clip_groups
            SET director_status = 0, director_error = NULL,
                classic_status = 0, merge_error = NULL, quality_issue = NULL
            WHERE id IN ({})
        """.format(",".join("?" * len(ids)))
    else:
        # 只重置失败（-1）和未开始（0）的，不动运行中（1）和已完成（2）
        reset_sql = """
            UPDATE clip_groups
            SET director_status = CASE WHEN director_status IN (-1, 0) THEN 0 ELSE director_status END,
                director_error   = CASE WHEN director_status IN (-1, 0) THEN NULL ELSE director_error END,
                classic_status   = CASE WHEN classic_status IN (-1, 0) THEN 0 ELSE classic_status END,
                merge_error      = CASE WHEN classic_status IN (-1, 0) THEN NULL ELSE merge_error END,
                quality_issue    = NULL
            WHERE id IN ({})
        """.format(",".join("?" * len(ids)))

    if dry_run:
        print(f"[DRY-RUN] 将重置 {len(ids)} 个分组状态")
    else:
        con.execute(reset_sql, ids)
        con.commit()
        print(f"✅ 已在 DB 中重置 {len(ids)} 个分组状态\n")
    con.close()

    # 3. 逐个调用 trigger_merge 端点
    print(f"🚀 开始触发双版本剪辑（每隔 {DELAY_BETWEEN_CALLS}s 发一个请求）\n")
    success = 0
    fail = 0

    for i, row in enumerate(targets, 1):
        gid = row['id']
        label = row['label'][:25] if row['label'] else "(无标签)"
        dir_s = STATUS_LABEL.get(row['director_status'], '?')
        cls_s = STATUS_LABEL.get(row['classic_status'], '?')

        print(f"[{i:>2}/{len(targets)}] id={gid} 「{label}」  导演:{dir_s} 经典:{cls_s}")

        if dry_run:
            print(f"         [DRY-RUN] POST {API_BASE}/api/groups/{gid}/merge")
            success += 1
        else:
            resp = http_post(f"{API_BASE}/api/groups/{gid}/merge")
            if "error" in resp:
                print(f"         ❌ 失败: {resp['error']}")
                fail += 1
            else:
                print(f"         ✅ 已触发: {resp}")
                success += 1

        if i < len(targets):
            time.sleep(DELAY_BETWEEN_CALLS)

    print(f"\n{'='*55}")
    if dry_run:
        print(f"[DRY-RUN] 将触发 {success} 个分组的双版本剪辑")
    else:
        print(f"完成！触发成功: {success}  失败: {fail}")
        print(f"\n💡 后续提示：")
        print(f"   • 经典版和导演版各用独立 Semaphore 串行处理，互不阻塞")
        print(f"   • 在前端 Groups 页面或 /api/groups 查看实时进度")
        print(f"   • 如有分组仍失败，可单独在前端点击「重新剪辑」")


if __name__ == "__main__":
    main()
