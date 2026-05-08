#!/usr/bin/env python3
"""
migrate_old_recordings.py — 将一周前的录像文件迁移到 10.190.0.218 的归档存储

迁移逻辑：
  - 源：GPU 服务器 (10.190.0.203) C:/Users/neo/douyin_recordings/<room_id>/
  - 目标：10.190.0.218  D:/douyin-recording/<room_id>/
  - 条件：文件创建时间 > MIGRATE_DAYS 天前（默认 7 天）
  - 迁移完成后删除源文件，释放 GPU 服务器空间
  - 支持 --dry-run 预览

配置：
  - 目标共享路径通过 MIGRATE_DEST 环境变量覆盖
  - SMB 认证通过 MIGRATE_USER / MIGRATE_PASS 环境变量设置
  - 默认目标：\\10.190.0.218\douyin-recording

用法：
  python3 scripts/migrate_old_recordings.py           # 正式迁移
  python3 scripts/migrate_old_recordings.py --dry-run # 预览
  python3 scripts/migrate_old_recordings.py --notify  # 迁移完成后推送通知

cron 调度（每周一 00:00 Asia/Shanghai）：
  已由 OpenClaw cron job 管理
"""

import os
import sys
import time
import subprocess
import argparse
import json
import datetime
import sqlite3

# ── 配置 ───────────────────────────────────────────────────────────────────
GPU_HOST       = "neo@10.190.0.203"
GPU_SOURCE_DIR = "C:/Users/neo/douyin_recordings"    # GPU 服务器录像目录
DEST_HOST      = "10.190.0.218"
DEST_SHARE     = os.environ.get("MIGRATE_DEST", "douyin-recording")  # SMB 共享名
DEST_DIR_WIN   = f"D:\\douyin-recording"             # 218 上的目标路径
MIGRATE_DEST_UNC = f"\\\\{DEST_HOST}\\{DEST_SHARE}" # UNC 路径

MIGRATE_USER   = os.environ.get("MIGRATE_USER", "")  # SMB 用户名（如需）
MIGRATE_PASS   = os.environ.get("MIGRATE_PASS", "")  # SMB 密码（如需）

MIGRATE_DAYS   = int(os.environ.get("MIGRATE_DAYS", "7"))  # 几天前的文件

DB_PATH        = "/Users/claw/work/douyin-recorder/douyin.db"
LOG_FILE       = "/private/tmp/migrate_recordings.log"

# ── 工具函数 ───────────────────────────────────────────────────────────────

def log(msg: str):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass

def notify(msg: str):
    try:
        subprocess.run(
            ["openclaw", "system", "event", "--text", msg, "--mode", "now"],
            capture_output=True, timeout=10
        )
    except Exception:
        pass

def ssh_run(cmd: str, timeout: int = 60) -> tuple[int, str, str]:
    """在 GPU 服务器上执行命令。"""
    result = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes",
         GPU_HOST, cmd],
        capture_output=True, timeout=timeout
    )
    # GPU 服务器 Windows 控制台输出为 GBK/CP936，用 errors='replace' 容错
    def _decode(b):
        for enc in ('utf-8', 'gbk', 'cp936', 'latin-1'):
            try:
                return b.decode(enc)
            except Exception:
                continue
        return b.decode('latin-1')
    return result.returncode, _decode(result.stdout), _decode(result.stderr)

def ssh_ps(ps_cmd: str, timeout: int = 60) -> tuple[int, str, str]:
    """在 GPU 服务器上执行 PowerShell 命令。"""
    return ssh_run(f'powershell -NonInteractive -command "{ps_cmd}"', timeout)


# ── 步骤 1：列出 GPU 上需要迁移的文件 ────────────────────────────────────────

def list_files_to_migrate() -> list[dict]:
    """通过 SSH 列出 GPU 服务器上超过 MIGRATE_DAYS 天的录像文件。"""
    cutoff_ts = time.time() - MIGRATE_DAYS * 86400
    cutoff_dt = datetime.datetime.fromtimestamp(cutoff_ts).strftime("%Y-%m-%dT%H:%M:%S")

    log(f"列出 {GPU_SOURCE_DIR} 中 {MIGRATE_DAYS} 天前的文件（截止 {cutoff_dt}）...")

    ps_cmd = (
        f"Get-ChildItem -Path '{GPU_SOURCE_DIR}' -Recurse -File "
        f"| Where-Object {{ $_.LastWriteTime -lt (Get-Date '{cutoff_dt}') }} "
        f"| Select-Object FullName, Length, @{{N='RoomDir';E={{$_.Directory.Name}}}} "
        f"| ConvertTo-Json -Compress"
    )
    rc, out, err = ssh_ps(ps_cmd, timeout=60)

    if rc != 0:
        log(f"  列出文件失败: {err[:200]}")
        return []

    if not out.strip():
        return []

    try:
        items = json.loads(out.strip())
        if isinstance(items, dict):
            items = [items]
        files = []
        for item in items:
            full = item.get("FullName", "").replace("\\", "/")
            size = item.get("Length", 0)
            room = item.get("RoomDir", "")
            if full and size:
                files.append({"path": full, "size": size, "room": room})
        return files
    except Exception as e:
        log(f"  解析文件列表失败: {e}, raw: {out[:200]}")
        return []


# ── 步骤 2：检查目标路径是否可达 ──────────────────────────────────────────────

def check_dest_reachable() -> bool:
    """在 GPU 服务器上检查 218 的 SMB 共享是否可访问。"""
    log(f"检查目标共享 {MIGRATE_DEST_UNC}...")

    # 先尝试直接挂载
    if MIGRATE_USER and MIGRATE_PASS:
        net_use_cmd = (
            f"net use {MIGRATE_DEST_UNC} /user:{MIGRATE_USER} {MIGRATE_PASS} /PERSISTENT:NO 2>&1"
        )
    else:
        net_use_cmd = f"net use {MIGRATE_DEST_UNC} /PERSISTENT:NO 2>&1"

    rc, out, err = ssh_run(net_use_cmd, timeout=20)
    if rc == 0 or "命令成功完成" in out or "The command completed" in out:
        log(f"  SMB 挂载成功: {MIGRATE_DEST_UNC}")
        return True

    # 尝试直接访问（可能已有缓存凭证）
    rc2, out2, _ = ssh_ps(
        f"Test-Path '{MIGRATE_DEST_UNC}' -ErrorAction SilentlyContinue",
        timeout=15
    )
    if "True" in out2:
        log(f"  目标路径可访问")
        return True

    log(f"  ❌ 目标不可达: {out[:200]} {err[:100]}")
    log(f"  提示：请确认 10.190.0.218 的共享名，或设置环境变量 MIGRATE_USER / MIGRATE_PASS")
    return False


# ── 步骤 3：执行迁移 ──────────────────────────────────────────────────────────

def migrate_files(files: list[dict], dry_run: bool) -> tuple[int, int, int]:
    """
    迁移文件列表到 218。
    返回 (成功数, 失败数, 跳过数)。
    """
    ok = failed = skipped = 0

    # 按 room_id 分组迁移（提升效率）
    by_room: dict[str, list[dict]] = {}
    for f in files:
        by_room.setdefault(f["room"], []).append(f)

    for room, room_files in by_room.items():
        dest_room = f"{MIGRATE_DEST_UNC}\\{room}"

        # 确保目标 room 目录存在
        if not dry_run:
            rc, _, _ = ssh_ps(
                f"New-Item -ItemType Directory -Force -Path '{dest_room}' | Out-Null; Write-Host ok",
                timeout=10
            )

        for finfo in room_files:
            src = finfo["path"].replace("/", "\\")
            fname = os.path.basename(src)
            dest_file = f"{dest_room}\\{fname}"
            size_mb = finfo["size"] / 1024 / 1024

            if dry_run:
                log(f"  [dry-run] {room}/{fname} ({size_mb:.1f} MB) → {dest_file}")
                skipped += 1
                continue

            log(f"  迁移 {room}/{fname} ({size_mb:.1f} MB)...")

            # 用 robocopy 复制（断点续传，自动重试）
            rc, out, err = ssh_run(
                f'robocopy "{os.path.dirname(src)}" "{dest_room}" "{fname}" '
                f'/R:2 /W:5 /MT:4 /NFL /NDL /NJH /NJS 2>&1',
                timeout=300
            )
            # robocopy 返回 0-7 都是成功（>=8 才是错误）
            if rc <= 7:
                # 验证目标文件存在后删除源文件
                rc2, out2, _ = ssh_ps(
                    f"Test-Path '{dest_file}' -ErrorAction SilentlyContinue",
                    timeout=10
                )
                if "True" in out2:
                    # 删除源文件
                    rc3, _, _ = ssh_run(f'del /F /Q "{src}" 2>&1', timeout=10)
                    if rc3 == 0:
                        log(f"    ✅ 已迁移并删除源文件")
                        ok += 1
                    else:
                        log(f"    ⚠️  已复制但删除源文件失败（不影响数据）")
                        ok += 1  # 数据已安全，算成功
                else:
                    log(f"    ❌ 复制后目标文件不存在，保留源文件")
                    failed += 1
            else:
                log(f"    ❌ robocopy 失败 (rc={rc}): {out[:100]}")
                failed += 1

    return ok, failed, skipped


# ── 步骤 4：更新本地 DB 标记 ─────────────────────────────────────────────────

def mark_migrated_in_db(migrated_rooms: list[str], cutoff_ts: float):
    """（可选）在本地 DB 记录迁移状态，防止重复处理。"""
    # 目前 DB 没有 archived 字段，跳过；若以后需要可在这里扩展
    pass


# ── 主函数 ───────────────────────────────────────────────────────────────────

def main():
    global MIGRATE_DAYS
    parser = argparse.ArgumentParser(description="将一周前的录像从 GPU 服务器迁移到 10.190.0.218")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际迁移")
    parser.add_argument("--notify", action="store_true", help="完成后推送 OpenClaw 通知")
    parser.add_argument("--days", type=int, default=MIGRATE_DAYS, help=f"迁移 N 天前的文件（默认 {MIGRATE_DAYS}）")
    args = parser.parse_args()

    MIGRATE_DAYS = args.days

    log("=" * 60)
    log(f"录像归档迁移 {'[DRY-RUN]' if args.dry_run else '[正式迁移]'} (>{MIGRATE_DAYS}天前)")
    log(f"源：{GPU_HOST}:{GPU_SOURCE_DIR}")
    log(f"目标：{MIGRATE_DEST_UNC}")
    log("=" * 60)

    # 1. 列出待迁移文件
    files = list_files_to_migrate()
    if not files:
        log("无需迁移的文件（没有超期录像）")
        log("=" * 60)
        if args.notify:
            notify("📦 录像归档：无需迁移的文件")
        return

    total_size = sum(f["size"] for f in files) / 1024 / 1024 / 1024
    log(f"待迁移：{len(files)} 个文件，共 {total_size:.2f} GB")

    # 2. 检查目标可达性
    if not args.dry_run:
        if not check_dest_reachable():
            log("❌ 目标不可达，迁移中止")
            if args.notify:
                notify(f"❌ 录像归档失败：无法访问 {MIGRATE_DEST_UNC}\n请检查 10.190.0.218 共享配置")
            sys.exit(1)

    # 3. 执行迁移
    ok, failed, skipped = migrate_files(files, args.dry_run)

    log("=" * 60)
    if args.dry_run:
        log(f"[dry-run] 预计迁移 {len(files)} 个文件 ({total_size:.2f} GB)")
    else:
        log(f"迁移完成：成功={ok}  失败={failed}  跳过={skipped}")

    log("=" * 60)

    if args.notify and not args.dry_run:
        if failed == 0:
            notify(
                f"📦 录像归档完成：{ok} 个文件 ({total_size:.1f} GB) 已迁移到 {DEST_HOST}\n"
                f"GPU 服务器空间已释放"
            )
        else:
            notify(
                f"⚠️ 录像归档部分失败：成功 {ok}，失败 {failed}\n"
                f"请检查 {LOG_FILE}"
            )

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
