# douyin-recorder Codex 交接报告

生成时间：2026-08-10 12:13（Asia/Shanghai）
项目：`douyin-recorder`
仓库：`/Users/claw/work/douyin-recorder`
GitHub：`https://github.com/neo9su/autoclipvideo`
基线分支：`master`
部署分支：`master`
技术栈：FastAPI + SQLite + Vue/Vite + 远端 GPU backend

> 本报告只记录已由工具、代码、远端 HTTP、GPU job 或 Issue/PR runtime 证实的事实。Issue CLOSED、PR 存在/merged、Doing、To Do、slot 不等于业务完成。

## 1. 项目概况

### 运行角色

- 本机控制面：`127.0.0.1:8099`，当前实际进程是旧的 `uvicorn app.server:app` 实例；其 OpenAPI 未出现预期 `/api/v2/*` 路由。
- 远端 GPU backend：`http://10.190.0.203:8899`。
- 远端 GPU 服务：`http://10.190.0.203:8877`。
- 远端 STT：`http://10.190.0.203:8098`，健康检查 HTTP 200，设备显示 CUDA。
- 远端 8899 `/health`：HTTP 200，`deployment_role=gpu-backend`，版本 `MVP1.04.2026032501`。

### 主要目录

- `backend/`：FastAPI 主服务、业务 API、编辑/转录/导演/千川管线。
- `frontend/`：Vue/Vite 前端。
- `gpu_service/`：远端 GPU 服务源码/运维脚本。
- `scripts/`：部署、批处理、审计、监控脚本。
- `deploy/`：Docker compose、远端验证脚本、部署示例。
- `tests/`、`runner/tests/`：测试。
- `recordings/`：本机录像库；包含 MP4、SRT、按房间/日期分类的子目录。该目录约 1.3 TB，未打包进交接压缩包。
- `voice_output/`：约 4.2 GB，未打包。
- `logs/`：约 414 MB，未整体打包，仅保留必要说明。

## 2. 当前真实状态

### #120：Fabrica 可靠性状态机研究

- Issue：OPEN，`To Research / active`。
- worker：有 `firstWorkerActivityAt`。
- `sessionCompletedAt=null`，`hasArtifact=false`，无 PR。
- 研究没有收敛，当前受阻。不能将 active 或 worker activity 当作完成。

链接：`https://github.com/neo9su/autoclipvideo/issues/120`

### #121：durable coordinator / fenced worker lifecycle

- Issue：CLOSED。
- worker 有 first activity，session 已完成，artifact 存在。
- PR #124 的汇总状态为 merged，但 Fabrica 绑定字段曾显示 open，存在状态不一致。
- 这是代码/worker 产物证据，不是线上部署和业务 smoke 完成证据。
- 未取得独立完整测试矩阵和部署 smoke 归档。

链接：`https://github.com/neo9su/autoclipvideo/issues/121`
PR：`https://github.com/neo9su/autoclipvideo/pull/124`

### #123：当前主修复

- Issue：CLOSED。
- worker 有 first activity，session 已完成，artifact 存在。
- PR #125 的汇总状态为 merged，但绑定字段曾显示 open，存在状态不一致。
- 主修复代码有产物，但完整业务验收仍未完成：缺独立完整测试矩阵、部署审计和三版本线上 smoke。
- 不得因为 Issue/PR CLOSED/merged 宣称 #123 完成。

链接：`https://github.com/neo9su/autoclipvideo/issues/123`
PR：`https://github.com/neo9su/autoclipvideo/pull/125`

### #126：从真实录像重建经典版、导演版和千川版

- Issue：OPEN，通常显示 `To Do`。
- runtime 长期为 `accepted_idle`。
- `firstWorkerActivityAt=null`、`sessionCompletedAt=null`、`hasArtifact=false`。
- `sessions_list` 多次返回 0；存在 worker session 未启动/丢失问题。
- PR #127 open 且 `mergeable=false`，PR 存在不代表任务开始。
- 该任务的核心不是找字幕文字：用户已明确只需确认 MP4，字幕可后续重新生成。

链接：`https://github.com/neo9su/autoclipvideo/issues/126`
PR：`https://github.com/neo9su/autoclipvideo/pull/127`

### #134：修复远端 GPU 千川 API 路由并完成真实 smoke

- #126 的子任务，Issue OPEN。
- 当前 runtime 曾反复 `accepted_idle`；最近一次已有 `firstWorkerActivityAt`，但 `sessionCompletedAt=null`、`hasArtifact=false`。
- PR #135 open、mergeable=true，但不等于已部署或 smoke 通过。
- 任务必须核实远端运行 commit、进程、部署同步，修复 `/api/v2/qianchuan/*` 并提交真实千川请求。

链接：`https://github.com/neo9su/autoclipvideo/issues/134`
PR：`https://github.com/neo9su/autoclipvideo/pull/135`

### 其他当前未解决/排队项

- #130：建立可恢复的全量录像重剪与远端 GPU 文件访问流程；曾出现 `accepted_idle`、无 firstWorkerActivity、无 artifact，PR #133 open。不要把 Doing/PR 当完成。
- #122：三遍深挖 Fabrica accepted_idle 根因与替代架构；`To Research / active`，有 first activity，但未完成、无 artifact。
- #117：研究 Fabrica worker 持续故障根因；当前在 To Research 队列。

## 3. 已完成的真实视频处理证据

使用本机已存在的完整 MP4 作为输入，并直接调用远端 GPU 服务验证，绕过了失效的 Fabrica worker bootstrap：

### 经典版

- GPU clip job：`93b5c3258bee404d`
- 状态：`processing -> done`
- 输出通过远端 `/clip-jobs/{job_id}/mp4` 取得，本机临时证据约 61 MB。

### 导演版

- GPU director job：`dir_e4c11155f24d`
- 状态：`processing -> done`
- 输出通过远端 `/director-jobs/{job_id}/mp4` 取得，本机临时证据约 81 MB。

### 千川版

- 尚未启动。
- 远端 8899 OpenAPI 当前只有下载接口：
  - `/api/groups/{group_id}/qianchuan-preview-download`
  - `/api/groups/{group_id}/qianchuan-download`
- 缺少：`/api/v2/qianchuan/status`、`/generate`、`/compose`。
- 实测 `/api/v2/qianchuan/status` 返回 404；尝试 `/api/v2/qianchuan/generate` 返回 405。
- 不能把 creative 或普通 director job 当成千川结果。

## 4. 千川路由丢失的已知根因

源码中已经存在：

- `backend/api_v2.py` 定义 `qianchuan_router = APIRouter(prefix="/api/v2/qianchuan")`。
- `backend/main.py` 在 `DEPLOYMENT_ROLE=gpu-backend` 分支中应 `include_router(qianchuan_router)`。

但实际运行的本机/远端服务 OpenAPI 都没有该 router。已确认的最可能原因是部署不同步：

1. 路由代码只在当前源码/提交中，未同步到远端实际运行目录；或
2. 远端服务没有重启到包含路由的版本；或
3. `api_v2` 导入时发生 ImportError，且 `main.py` 当前只记录 warning 后跳过路由，导致服务仍能启动但路由静默缺失。

尚未取得远端启动日志/运行 commit，因此不能断言具体是 1、2、还是 3。#134/#135 的验收必须补齐这部分证据。

## 5. 代码与部署注意事项

- 当前工作树不是干净状态，存在本地未提交修改和大量未跟踪文件；Codex 接手前先保存/审阅，不要直接 reset 或清理。
- 重要已修改文件：`backend/main.py`、`backend/qianchuan_matcher.py`、`backend/transcribe.py`、`frontend/vite.config.js`、`scripts/gpu_monitor.py`、`douyin.db`。
- `.env`、数据库、录像、日志包含本地环境/运行数据；交接包已排除 `.env`、`.git`、大体量媒体、node_modules、数据库备份。
- 本机 `master` HEAD：`1fec4d4 Merge pull request #102 from neo9su/feature/101-douyin-recorder`。
- 近期相关提交：`854fa15 fix: clarify 8099 control-plane vs 8899 GPU-backend API routing (#74)`、`361026f fix: auto-fill missing Qianchuan policy fields in batch pipeline`、`b017bfd fix: disable SRT blocking in batch script`。

## 6. 建议 Codex 的执行顺序

1. 先读取本报告和 `CODEX_NEXT_STEPS.md`，检查当前 git diff 与远端部署脚本。
2. 核对远端 8899 的实际进程启动命令、工作目录、commit/hash 和启动日志；确认 `api_v2` 是否 ImportError。
3. 修复并部署千川 router，重启远端 backend；验证 OpenAPI 和 `/api/v2/qianchuan/status` HTTP 200。
4. 用已有上传临时组/录像组提交真实千川请求；记录 request、response、job_id、状态、输出路径/大小或真实门禁失败。
5. 运行代码测试和完整业务矩阵：经典、导演、千川、GPU-only、路由、SRT 可后续生成、媒体挂载、部署 smoke。
6. 只在所有证据归档后，才更新 Issue 状态；不得用 work queue、slot、Doing、PR merged 替代运行证据。

## 7. 不能宣称完成的项目

截至本报告生成时，以下均不能宣称完成：

- #120 研究未收敛；
- #126 三版本业务重建未完成；
- #134 千川路由未完成部署/smoke；
- #123 虽已 CLOSED/PR merged，但缺完整测试矩阵、部署和线上 smoke，因此按用户要求不能宣称业务完成；
- #121 缺独立部署/smoke 证据。

## 8. 证据边界

- “未发现明确测试失败”不等于“测试通过”。
- “GPU job done”只证明对应的远端 job 完成，不证明 Fabrica pipeline、部署或完整业务验收完成。
- 本报告中所有 `accepted_idle`、`firstWorkerActivityAt=null`、session/artifact 状态均来自 `doctor_issue` / `sessions_list` 实时工具结果。
