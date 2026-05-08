#!/usr/bin/env bash
# ============================================================
# 一键恢复脚本 — douyin-recorder
# 恢复到 pre-httpx-aiohttp-fix-20260424_0938
# 创建时间：2026-04-24
# ============================================================
set -e

RESTORE_TAG="pre-httpx-aiohttp-fix-20260424_0938"
DB_BACKUP="douyin.db.backup.20260424_0938"
PROJECT_DIR="/Users/claw/work/douyin-recorder"
BACKEND_PORT=8899

echo "========================================="
echo " douyin-recorder 一键恢复"
echo " 恢复目标: $RESTORE_TAG"
echo "========================================="

# 1. 停止后端
echo ""
echo "[1/4] 停止后端服务..."
PIDS=$(lsof -ti:$BACKEND_PORT 2>/dev/null || true)
if [ -n "$PIDS" ]; then
  kill $PIDS && echo "  ✅ 后端已停止 (PID: $PIDS)"
else
  echo "  ℹ️  后端未运行"
fi
sleep 1

# 2. 恢复代码
echo ""
echo "[2/4] 恢复代码到 $RESTORE_TAG..."
cd "$PROJECT_DIR"
git stash 2>/dev/null && echo "  ✅ 当前改动已 stash" || echo "  ℹ️  无未提交改动"
git checkout "$RESTORE_TAG"
echo "  ✅ 代码已恢复"

# 3. 恢复数据库
echo ""
echo "[3/4] 恢复数据库..."
if [ -f "$PROJECT_DIR/$DB_BACKUP" ]; then
  cp "$PROJECT_DIR/$DB_BACKUP" "$PROJECT_DIR/douyin.db"
  echo "  ✅ 数据库已从 $DB_BACKUP 恢复"
else
  echo "  ⚠️  找不到 $DB_BACKUP，跳过数据库恢复"
fi

# 4. 重启后端
echo ""
echo "[4/4] 重启后端..."
cd "$PROJECT_DIR/backend"
nohup uvicorn main:app --host 0.0.0.0 --port $BACKEND_PORT >> /private/tmp/douyin_backend.log 2>&1 &
sleep 2
NEW_PIDS=$(lsof -ti:$BACKEND_PORT 2>/dev/null || true)
if [ -n "$NEW_PIDS" ]; then
  echo "  ✅ 后端已启动 (PID: $NEW_PIDS)"
else
  echo "  ❌ 后端启动失败，请手动检查 /private/tmp/douyin_backend.log"
  exit 1
fi

echo ""
echo "========================================="
echo " ✅ 恢复完成！"
echo " 后端日志: tail -f /private/tmp/douyin_backend.log"
echo "========================================="

# 恢复完成后发送 OpenClaw 通知
/opt/homebrew/bin/openclaw system event --text "✅ douyin-recorder 已恢复到 $RESTORE_TAG" --mode now 2>/dev/null || true
