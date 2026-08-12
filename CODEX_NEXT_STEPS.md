# Codex 接手下一步

## 立即执行

1. 不要把 `Doing`、To Do、active slot、PR open/merged 当作完成证据。
2. 检查 `git status`、`git diff`，保存当前工作树，不要 reset/clean。
3. 核对远端 `10.190.0.203:8899` 的实际运行目录、进程、commit/hash、启动日志。
4. 重点检查 `backend/main.py`：GPU backend 分支是否成功导入 `api_v2`，是否执行 `app.include_router(qianchuan_router)`；不要让 ImportError 静默隐藏。
5. 部署并重启远端 backend 后验证：
   - `GET /health` → 200
   - `GET /openapi.json` 包含 `/api/v2/qianchuan/status`、`/generate`、`/compose`
   - `GET /api/v2/qianchuan/status` → 200
6. 用已有真实 MP4 提交千川请求；保存 HTTP response、job_id、状态轮询、输出文件/大小或明确门禁失败。
7. 再跑完整测试矩阵和部署/smoke，最后才考虑更新 Issue。

## 当前已知业务证据

- 经典版 GPU job：`93b5c3258bee404d`，`processing → done`。
- 导演版 GPU job：`dir_e4c11155f24d`，`processing → done`。
- 千川版：未启动；远端路由缺失，status 404、generate 405。

## 用户约束

- 录像 MP4 已在 `/Users/claw/work/douyin-recorder/recordings/`，包括按日期分类的子目录。
- 不要把字幕文字搜索作为前置阻塞；字幕可后续重新生成。
- #123 完整测试矩阵完成前，不得宣称完成。
- 不要调用 `work_finish` 伪造收敛。
