# Issue 247：远端 GPU worker 8877 只读复测报告

**采集时间：2026-08-21 17:46–17:49（Asia/Shanghai，UTC 09:46–09:49）**

## 安全边界

本次只执行了监控主机发起的 TCP connect、HTTP `GET` 和现有只读诊断脚本。未执行重启、停止、强杀、服务启动、队列 flush、GPU/Qianchuan retry、任务取消、视频重跑或数据库/媒体写入；没有主动改变 Qianchuan 队列或录制队列。

## 端点与 8899/8877 对比

使用 `scripts/diagnose_remote_endpoints.py --host 10.190.0.203 --cycles 3 --interval 1 --timeout 3` 连续采样：

| 端点 | 3 次 TCP | 3 次 HTTP | 当前判断 |
|---|---:|---:|---|
| `10.190.0.203:8899` `/api/monitor/status` | 3/3 成功 | 3/3 HTTP 200 | backend 可达 |
| `10.190.0.203:8877` `/health` | 3/3 成功 | 3/3 HTTP 200 | GPU worker 可达 |
| `10.190.0.203:22` | TCP 成功 | SSH 认证失败 | 主机端口可达，但本次无法进入主机 |

因此，监控发现的 `8877 connection refused` 在本次复测中**未复现**。当前不是端口冲突或网络不可达证据：8877 正在监听并能返回健康响应；8899 到 8877 的应用探测也已恢复为 `reachable=true`、`gpu_online=true`、`gpu_offline_seconds=0`。

### 8899 `/health`

- HTTP 200，`deployment_role=gpu-backend`，`media_workers_enabled=true`。
- `qianchuan_api_loaded=true`。
- `qianchuan_pending=3595`、`qianchuan_running=0`、`qianchuan_done=0`、`qianchuan_failed=10`、`qianchuan_permanent_fail=716`。
- 版本为 `MVP1.04.2026032501`；录制策略仍为最短 28 秒、单段最长 2700 秒。

### 8899 `/api/gpu/status`

- HTTP 200；`reachable=true`、`online=true`、`gpu_online=true`、`gpu_offline_seconds=0`。
- 远端 URL 为 `http://10.190.0.203:8877`。
- 远端 GPU health：`status=ok`、`health=healthy`、PID `1616`、CUDA 可用、设备为 RTX 4080 SUPER。
- `gpu_busy=false`、`queue_depth=0`、`clip_jobs_running=0`、`clip_jobs_pending=0`、`transcription_watchdog.active_tasks=0`、`concat_jobs_active=0`；`jobs=[]`。
- ComfyUI 只读探测可达，`queue_running=0`、`queue_pending=0`。
- 8899 的 `watchdog_probe`/`watchdog` 仍显示不可用，但这不等同于 8877 不可达；8877 的直接 health 和 backend GPU probe 均成功。

### 8877 `/health`

直接 GET 返回 HTTP 200，内容与 8899 代理看到的 GPU health 一致：服务为 `gpu`、状态 `healthy`，CUDA 可用，GPU/clip/concat/active task 均为空闲。

## listener/process/service/log 证据边界

- **listener：** 监控主机对 8877 连续三次 TCP connect 成功，且直接 `/health` HTTP 200；这足以确认当前存在可接受连接的监听服务，并排除当前“端口无人监听/端口冲突导致拒绝”的判断。
- **process：** 8899 `/api/gpu/status` 与 8877 `/health` 均报告 PID `1616`、健康状态和启动时间字段；本次未对该 PID 执行任何操作。
- **service manager / 本机端口清单：** SSH 22 虽可建立 TCP 连接，但使用的只读 SSH 登录未通过认证（`Permission denied`）。因此本次无法读取 Windows service/scheduled-task、`netstat`/进程清单或服务管理器事件；不能把 API 报告冒充成本机 PowerShell 证据。
- **log：** 通过 8899 的只读 `/api/gpu/logs` 可读到近期记录，包含 14:49 转录完成、14:12 `bad allocation` 失败，以及更早的 `service restarted` 失败记录。该接口未显示当前 8877 仍在离线；它不能替代 worker 主机原始日志，因此无法确认 17:36 前后是谁恢复了服务。

## 队列、活跃任务与安全恢复判断

额外只读 GET 结果：

- `/api/monitor/status` HTTP 200：监控运行中，`recording=0`，`pending_recordings=6313`，`pending_publish=0`。
- `/api/status` HTTP 200：`active_recordings=0`。
- `/api/transcribe-queue` HTTP 200：`jobs=[]`、`total=0`。
- `/api/clip-queue` HTTP 200：`running=[]`、`queued=[]`、`paused=[]`、`total_queued=0`。
- `/api/watchdog/status` HTTP 200：返回空对象；不能据此证明 watchdog 进程存在或不存在。

当前 8877 已健康，且 Qianchuan 仍有 3595 个 pending 项。虽然 GPU health 没有 active/busy task，但 Qianchuan pending 队列和后端 worker 仍是生产状态；本次没有必要、也没有足够权限证据执行重启。**未执行任何恢复动作**，保持服务、Qianchuan 和既有队列不变。建议由有权限的 GPU 主机管理员补采服务管理器事件、8877 进程/监听清单和原始日志，确认短暂 refused 的实际恢复来源。

## 4675–4694 五版本可见性

对当前 8899 的只读 `/api/groups` 完整读取后按 ID 过滤：响应共 4321 个分组，目标 `4675–4694` **均未出现在当前响应**。当前生产 API 因此无法提供这 20 个分组的实时五版本状态；本次没有调用任何 POST retry/generate 路由，也没有重跑已成功视频。

仓库历史只读记录仅作为背景，不能当作本次生产快照：

- 4675–4684：历史记录为缺少源媒体，禁止盲目 retry。
- 4687：历史记录为商品强匹配不足。
- 4685–4686、4688–4694：历史记录曾记录 Qianchuan 成功/ready，但当前 API 未返回这些分组，不能据此断言当前文件仍存在。

## 结论

1. **当前状态：** 8877 已恢复可达且健康；8899 health 与 GPU status 均正常，`gpu_offline_seconds=0`。
2. **故障分类：** 17:36 的 refused 不是当前网络持续故障，也不是当前端口冲突；在缺少 GPU 主机服务管理器/原始日志的情况下，无法进一步区分此前是 worker 短暂停止、服务管理恢复还是瞬态防火墙/网络抖动。状态误报的可能性低，因为 8877 直接 health 与 8899 backend probe 一致成功。
3. **动作：** 不重启、不停止、不强杀、不 retry、不 flush、不重跑；保持 Qianchuan pending=3595 和生产调度不变。
4. **后续：** 由具备远端登录权限的管理员补采只读 listener/process/service/log 证据；随后连续 5 次核验 8877 `/health`、8899 `/api/gpu/status`，并单独取得 4675–4694 的权威只读快照后再讨论任何恢复或补偿动作。
