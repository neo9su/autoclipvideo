# 导演模式回退指南

> **创建时间**: 2026-04-08 14:00  
> **基线版本**: director-mode-baseline (commit: e91e796)  
> **备份状态**: pre-director-mode-backup-20260408_1400

---

## 🔄 快速回退选项

### 1. 完全回退到基线版本（最安全）

```bash
cd /Users/claw/work/douyin-recorder

# 选项A：硬重置（丢失所有新改动）
git reset --hard director-mode-baseline

# 选项B：保留新文件，恢复原始版本
git checkout director-mode-baseline -- backend/ frontend/src/
```

### 2. 恢复暂存的工作状态

```bash
# 查看所有暂存
git stash list

# 恢复指定暂存
git stash pop stash@{0}  # 最新的：pre-director-mode-backup-20260408_1400
```

### 3. 仅回退导演模式相关文件

```bash
# 如果只想回退特定模块
git checkout director-mode-baseline -- backend/director/
git checkout director-mode-baseline -- backend/shadow_runner.py
# ... 其他新增文件
```

---

## 📂 基线版本信息

### 提交历史
```
e91e796 - Improve thumbnail sharpness and person detail clarity
cf11c14 - Fix auto-merge: handle skipped recordings and backfill on startup  
9da12ac - Align clip logic with 巨量千川 quality standards (v1.4.0)
53cba5f - Bump to v1.4.0: update docs and backup
```

### 项目状态
- **版本**: v1.5.0
- **数据库**: douyin.db（已备份当前状态）
- **GPU服务**: Python 3.11.9 稳定运行
- **功能完整性**: 转录、剪辑、发布全流程正常

---

## 🛡️ 数据安全

### 数据库备份
```bash
# 当前数据库已自动备份
cp douyin.db douyin.db.backup.20260408_1400

# 恢复数据库（如需要）
cp douyin.db.backup.20260408_1400 douyin.db
```

### 重要文件保护
- ✅ `recordings/` 目录不受影响
- ✅ GPU服务器数据不受影响  
- ✅ 发布账号cookie保持完整
- ✅ 商品库数据保护

---

## 🚨 紧急回退程序

### 如果导演模式导致系统异常

```bash
# 1. 立即停止后端
pkill -f "uvicorn main:app"

# 2. 回退代码
cd /Users/claw/work/douyin-recorder
git reset --hard director-mode-baseline

# 3. 恢复数据库
cp douyin.db.backup.20260408_1400 douyin.db

# 4. 重启后端
cd backend
nohup uvicorn main:app --host 0.0.0.0 --port 8899 > /tmp/douyin_backend.log 2>&1 &

# 5. 验证系统
curl http://localhost:8899/api/status
```

---

## 🔍 验证回退成功

### 关键检查点
1. **后端启动**: `curl http://localhost:8899/api/status`
2. **前端访问**: `http://localhost:5173`
3. **GPU服务**: `curl http://10.190.0.203:8877/status`
4. **转录队列**: 检查pending任务正常处理
5. **剪辑功能**: 手动触发一个剪辑任务验证

### 预期结果
- ✅ 系统返回经典剪辑模式
- ✅ 所有现有功能正常
- ✅ 数据库结构完整
- ✅ 无导演模式相关日志

---

## 📞 故障排查

### 如果回退后仍有问题

1. **检查数据库一致性**
   ```bash
   sqlite3 douyin.db ".schema" | grep -E "(director|script|voice)"
   # 应该没有导演模式相关字段
   ```

2. **清理缓存和临时文件**
   ```bash
   rm -rf backend/__pycache__/director*
   rm -rf backend/director/
   rm -f backend/*director*.py
   ```

3. **重建前端**
   ```bash
   cd frontend
   npm run build
   ```

---

**保存此文件，在实施导演模式前确认已完成所有备份步骤**