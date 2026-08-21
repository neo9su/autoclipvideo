# Issue #247 — 远端 GPU worker 8877 只读复测诊断

## 结论（2026-08-21 18:01 Asia/Shanghai）

- **8877 当前已恢复可达且服务正常**：从监控主机 TCP connect 成功，`GET http://10.190.0.203:8877/health` 返回 HTTP 200；响应为 `status=ok`、`health=healthy`、CUDA 可用、`gpu_busy=false`、`queue_depth=0`、`transcription_watchdog.active_tasks=0`。
- **8899 当前正常**：只读复测连续 3 个周期均 TCP 成功，`GET /api/monitor/status` 返回 HTTP 200；`GET /health` 返回 HTTP 200，`ok=true`、media workers 和 Qianchuan API 已加载。
- **不是当前端口冲突或持续网络故障**：两个端口均可建立 TCP 并返回应用响应；因此 17:36 观察到的 8877 connection refused / `gpu_offline_seconds≈519` 已不再复现。仅凭当前证据不能判断此前短暂不可达的根因是进程退出后自恢复、服务管理器恢复，还是网络路径瞬断。
- **没有执行恢复动作**：未重启、停止、强杀、flush、重试任务、改变队列或重跑视频。8877 已自行呈现健康状态，继续执行恢复动作没有安全收益。

## 只读采样证据

工具：`scripts/diagnose_remote_endpoints.py --host 10.190.0.203 --cycles 3 --interval 1 --timeout 2`

| 周期 | 时间（UTC） | 8899 TCP/HTTP | 8877 TCP/HTTP | 判断 |
|---|---|---|---|---|
| 1 | 10:01:40 | 成功 / 200 | 成功 / 200 | host_and_ports_reachable |
| 2 | 10:01:41–42 | 成功 / 200 | 成功 / 200 | host_and_ports_reachable |
| 3 | 10:01:43 | 成功 / 200 | 成功 / 200 | host_and_ports_reachable |

应用接口快照：

- `8899 /health`：`qianchuan_api_loaded=true`、`qianchuan_pending=3592`、`qianchuan_running=0`、`qianchuan_failed=12`、`qianchuan_permanent_fail=717`。
- `8899 /api/gpu/status`：`online=true`、`reachable=true`、`gpu_online=true`、`gpu_offline_seconds=0`；GPU health `healthy`，`pid=7388`，`jobs=18548`，`queue_depth=0`，`gpu_busy=false`，`transcription_watchdog.active_tasks=0`。`pending_transcribe=6313` 是后端待处理记录总量，不等同于 GPU 当前运行数。
- `8877 /health`：与 8899 GPU health 字段一致，`status=ok`、`health=healthy`、CUDA device 为 RTX 4080 SUPER、`queue_depth=0`、`active_tasks=0`。
- `8899 /api/transcribe-queue`：`jobs=[]`、`total=0`。
- `8899 /api/clip-queue`：`running=[]`、`queued=[]`、`paused=[]`、`total_queued=0`。
- `8899 /api/monitor/status`：backend `running=true`；四个 room 均 `recording=false`，没有活动录制。
- `watchdog`：`/api/gpu/status` 中 cached/direct watchdog probe 为 unavailable，但这不等同于 8877 不可达；8877 直接 health probe 已成功。8878/Watchdog 本身未执行写操作，也未将其误判为 GPU worker 状态。

## 主机级 listener/process/service/log 证据与限制

- TCP 22、8877、8899 均可达，说明监控主机到目标主机的路径当前可用。
- SSH 认证尝试返回 `Permission denied (publickey,password,keyboard-interactive)`。因此无法在目标 Windows 主机上安全读取 `Get-NetTCPConnection`、进程列表、服务管理器状态或日志尾部。
- 应用 health 响应提供了服务 PID、启动时间和 uptime（`pid=7388`、`uptime_s≈261`），但这只能作为应用层自报，**不能替代**远端 OS listener/process/service/log 审计。
- 没有因认证失败改用猜测凭据、重复认证、重启服务或任何写操作。

## Qianchuan 与 GPU 任务安全核对

- 监控发现时的 `qianchuan_pending=3595` 与复测时 `qianchuan_pending=3592` 不同；两次均 `qianchuan_running=0`。本次诊断没有主动改变 Qianchuan 状态，差异应视为监控时间点之间的自然状态变化，不能归因于本次探测。
- 8877 health 与 8899 GPU status 均显示 GPU 当前空闲：`gpu_busy=false`、`queue_depth=0`、`active_tasks=0`。转录队列和剪辑队列接口也均为空。
- 未执行任何会改变 Qianchuan pending/running、GPU queue 或 active tasks 的接口调用。

## 目标批次 4675–4694 五版本可见性

使用 `scripts/inventory_orphaned_recording_clips.py --clips 4675-4694` 对工作树内 SQLite 副本执行 `mode=ro` + `PRAGMA query_only=ON` 盘点，未写入数据库：

- `backend/douyin.db` 是唯一具有目标三表 schema 的本地副本；发现 10 个 clip（4685–4694），其关联 recording 不存在，故无法解析五版本状态。
- 4675–4684 在该副本中没有 recording clip 行；4685–4694 为 orphaned recording references。
- 五版本字段（`classic_status`、`director_status`、`creative_status`、`realistic_status`、`conservative_status`）在 schema 中可识别，但本地副本没有可关联的 `recordings`/`clip_groups` 行，故五版本状态均应记录为**不可见/未知**，不能推断成功或失败。
- 其他候选 SQLite 文件缺少所需 schema，不能作为目标批次权威来源。没有据此修复、删除、重建或重跑任何视频。
- 由于没有可用的远端数据库只读导出/API 分页结果，不能把工作树副本结论扩大为生产当前事实；需具备只读数据库/业务查询权限后再补齐批次状态。

## 安全处置与后续建议

当前不需要服务恢复动作：8877 已健康，且无 active GPU task。保持现状，不重启、不强杀、不 flush、不重试、不重跑。

若再次发生 8877 不可达，先按以下只读门槛采样：

1. 连续采样 8899 `/health`、8899 `/api/gpu/status`、8877 `/health`、SSH/TCP 22，并保存错误类型与时间。
2. 主机恢复可达后，使用已授权的只读 Windows 管理凭据核对 8877 listener、PID/启动时间、服务管理器状态、GPU 进程与日志尾部；不要先重启来“验证”。
3. 只有确认无 active GPU/Qianchuan task、服务进程已退出且取得人工批准时，才评估最小恢复动作。
4. 为 4675–4694 获取生产权威只读查询/导出后，再核对五版本状态；不重复重跑任何已成功视频。

## 安全边界

本次只执行 TCP connect、HTTP GET、SSH 可达性/认证检查和本地 SQLite 只读盘点；没有执行 POST/DELETE、服务控制、进程终止、数据库写入、队列操作或视频处理。
