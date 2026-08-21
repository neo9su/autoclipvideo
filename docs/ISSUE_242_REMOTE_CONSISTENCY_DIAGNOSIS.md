# Issue 242 — 远端 GPU worker/backend 一致性只读诊断

**采集时间：2026-08-21 13:06–13:08（GMT+8）**

## 安全边界

本次仅执行 TCP connect、HTTP `GET`、远端 PowerShell 只读进程/监听查询，以及本地只读脚本检查。未发送暂停、停止、retry、bulk generation、flush、重启或强杀命令；未修改生产数据库、媒体文件或队列；未重跑任何视频。

## 端点与服务证据

使用 `scripts/diagnose_remote_endpoints.py --host 10.190.0.203 --cycles 3 --interval 1 --timeout 2` 连续采样 3 次：

| 端点 | 结果 |
|---|---|
| `10.190.0.203:8899` | 3/3 TCP 可达，`GET /api/monitor/status` HTTP 200 |
| `10.190.0.203:8877` | 3/3 TCP 可达，`GET /health` HTTP 200 |
| `10.190.0.203:8878` | TCP 可达 |
| `10.190.0.203:8188` | TCP 可达 |
| SSH `22` | TCP 可达 |

8899 只读接口结果：

- `/health`: HTTP 200；`deployment_role=gpu-backend`，`media_workers_enabled=true`，`qianchuan_api_loaded=true`。
- `/api/status`: HTTP 200；`active_recordings=2`，`total_recordings=9812`。
- `/api/monitor/status`: HTTP 200；`running=true`，`rooms.recording=2`，`queue.pending_recordings=5543`，`queue.pending_publish=0`。
- `/api/gpu/status`: HTTP 200；`reachable=true`、`online=true`、`maintenance=false`，GPU `healthy`，`gpu_busy=false`，`queue_depth=0`，`clip_jobs_running=0`，`clip_jobs_pending=0`，`transcription_watchdog.active_tasks=0`，`concat_jobs_active=0`。
- `/openapi.json`: HTTP 200；Qianchuan status/generate/compose/result 路由均存在。
- `/api/groups`: HTTP 200，约 76.8 MB，返回 4321 个分组；这是一次只读请求，响应约 3.2 秒。此前观测到的部分 API timeout 未在本次复核中复现；该接口体量较大，客户端短超时仍可能表现为 timeout。

8877 `/health` 结果：

```json
{
  "status": "ok",
  "service": "gpu",
  "health": "healthy",
  "pid": 2188,
  "gpu_busy": false,
  "queue_depth": 0,
  "clip_jobs_running": 0,
  "clip_jobs_pending": 0,
  "transcription_watchdog": {"active_tasks": 0},
  "concat_jobs_active": 0
}
```

SSH 只读查询确认：

| 进程 | PID | 启动时间 | 监听 |
|---|---:|---|---|
| GPU worker `python` | 2188 | 2026-08-21 12:36:34 | `0.0.0.0:8877` |
| watchdog `python` | 3420 | 2026-08-21 12:22:27 | `0.0.0.0:8878` |
| ComfyUI `python` | 17728 | 2026-08-21 12:42:43 | `0.0.0.0:8188` |

未执行任何恢复动作，因此不能声称本次人工部署修复导致恢复。结合进程启动时间，8877 更可能是在本次采集前由既有服务管理流程/人工操作恢复；具体恢复者和 artifact/dispatch 记录仍无法从当前只读证据确定。

## Qianchuan 与忙碌任务保护

`/health` 报告：

- `qianchuan_pending=3602`
- `qianchuan_running=0`
- `qianchuan_done=0`
- `qianchuan_failed=7`
- `qianchuan_permanent_fail=712`
- `qianchuan_probe_fail=0`

GPU worker 报告无 active task、无 GPU busy、无 clip/concat running；backend 监控仍报告 2 个直播录制中的 active recordings。因未进行恢复/调度操作，未中断这些录制，也未触碰 Qianchuan pending 队列。

## 4675–4694 五版本只读验证

本次对当前 8899 的 `/api/groups` 做了完整只读读取并按 `id` 过滤。当前响应的 ID 范围为 `1–4643`，4321 个分组中**不存在 4675–4694**；对 `/api/v2/qianchuan/group/{id}/result` 逐一 GET 也全部返回 HTTP 404。因此当前远端 backend 无法为 4675–4694 提供实时 Qianchuan 或五版本状态，不能把历史文档中的状态冒充为本次生产证据。

历史只读记录 `docs/issue-223-qianchuan-diagnosis.md` 仅能作为背景：

- 4675–4684：历史记录为缺少源媒体，禁止盲目 retry。
- 4687：历史记录为商品强匹配不足，属于不同失败类型。
- 4685–4686、4688–4694：历史记录为 Qianchuan status 2 且有 ready artifact。

当前 worktree 不包含 `backend/douyin.db`（仅存在 SQLite WAL/SHM 文件），因此本地 `inventory_orphaned_recording_clips.py --clips 4675-4694` 与 `diagnose_qianchuan_missing_media.py` 无法形成有效数据库证据；两者均在打开数据库前失败，未写入任何数据。下一步必须从当前生产 backend 导出或通过只读 API 提供包含 4675–4694 的权威快照，再按五个版本逐组核验。

## 根因/下一步

- **8877 refused 的当前根因：** 已不再复现；现在 worker 已健康监听。仅凭本次证据不能确定此前 refused 是进程退出、服务管理恢复、网络路径抖动还是防火墙瞬态问题。需保留远端服务管理器事件/日志和网络设备日志，才能闭环归因。
- **8899 部分 API timeout：** 本次 `/api/groups` 成功但响应约 76.8 MB、耗时约 3.2 秒；这足以解释采用过短客户端超时的表现，但不能排除此前瞬时 backend/依赖拥塞。建议后续只读监测使用合理的响应超时并分别记录 connect、TTFB、total time，不要以短 timeout 触发恢复动作。
- **安全结论：** 当前无理由重启或强杀 GPU worker；健康数据明确无 busy/active GPU task，但 Qianchuan pending=3602，任何改变调度的操作仍需单独批准。先保持队列不动，补齐 4675–4694 的权威只读快照与服务恢复日志。
