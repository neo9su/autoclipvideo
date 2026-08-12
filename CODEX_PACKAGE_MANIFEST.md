# Codex 交接包文件清单

## 已包含

- `CODEX_HANDOFF_REPORT_ZH.md`：项目概况、真实状态、证据边界、未解决 issues、部署根因和建议顺序。
- `CODEX_NEXT_STEPS.md`：接手后的立即执行清单。
- `README.md`
- `PROJECT_SUMMARY.md`
- `PROJECT_DELIVERY.md`
- `MONITOR_BRIEFING.md`
- `DOUYIN_VIDEO_QUALITY_GUIDE.md`
- `DIRECTOR_MODE_DESIGN.md`
- `docs/GPU_ONLY_MEDIA_POLICY.md`
- `docs/REMOTE_GPU_SMB_ISOLATION.md`
- `docs/SMB_MEDIA_ISOLATION.md`
- `docs/OMNIVOICE_DEPLOYMENT.md`
- `deploy/verify-remote.sh`
- `deploy/docker-compose.gpu-backend.yml`
- `deploy/gpu-backend.env.example`
- `scripts/deploy_gpu_backend.sh`
- `scripts/batch_qianchuan_regen.py`
- `scripts/trigger_director_batches.py`
- `scripts/fix_director_creative.py`
- `scripts/qa.sh`
- `backend/main.py`
- `backend/api_v2.py`
- `backend/transcribe.py`
- `backend/editor.py`
- `backend/analyzer.py`
- `backend/director_video.py`
- `backend/qianchuan_*.py`
- `backend/sync.py`
- `backend/gpu_execution.py`
- `backend/local_media_guard.py`
- `gpu_service/main.py`
- `gpu_service/OPERATIONS.md`
- `gpu_service/requirements.txt`
- `tests/`
- `runner/tests/`

## 已排除

- `.git/`：避免交接包过大；原仓库仍保留完整 Git 历史。
- `recordings/`：约 1.3 TB，不打包；路径和使用说明在报告中。
- `voice_output/`：约 4.2 GB，不打包。
- `logs/`：约 414 MB，不整体打包。
- `frontend/node_modules/`、`.venv/`、`__pycache__/`、构建缓存。
- `.env`、本地 token/密钥和运行时私密配置。
- 大型 SQLite 数据库和数据库备份；接手者需使用本机原目录中的数据库并先备份。

## 重要安全提醒

交接包不包含 `.env`，Codex 需要在目标环境自行配置远端 URL、GPU 服务、数据库和认证信息。不要把本地密钥复制进报告或提交到仓库。
