# Issue 242：远端 GPU worker 与 backend 一致性只读报告

日期：2026-08-21（Asia/Shanghai）  
模式：只读诊断；未执行部署、重启、停止、暂停、重试、生成或批量命令。

## 结论

本次复核时远端已自行恢复，未执行恢复动作：

- `10.190.0.203:8899`：TCP 可达，`/health`、`/api/status`、`/api/monitor/status`、`/api/gpu/status` 和 Qianchuan status 均 HTTP 200。
- `10.190.0.203:8877`：TCP 可达，`/health` HTTP 200。
- 远端监听状态：`8899 -> PID 17336`，`8877 -> PID 2188`；两个进程均为 `python.exe` 且 Responding=True。
- backend 报告 `qianchuan_pending=3602`、`qianchuan_running=0`；GPU worker `queue_depth=0`、`gpu_busy=false`、`clip_jobs_running=0`、`clip_jobs_pending=0`、`active_tasks=0`；ComfyUI running/pending 也均为 0。
- backend 当前仍有 1 个 active recording（room 7 正在录制），因此任何停止、重启或部署恢复均不满足安全门槛，本次明确不执行。

## 采集证据

### 端点探测

`python3 scripts/diagnose_remote_endpoints.py --host 10.190.0.203 --timeout 5` 在 `2026-08-21T04:47:15Z` 记录：

```text
backend 8899: tcp_reachable=true, http_reachable=true, HTTP 200 (/api/monitor/status)
gpu     8877: tcp_reachable=true, http_reachable=true, HTTP 200 (/health)
diagnosis: host_and_ports_reachable, confidence=high
```

### backend 健康与队列

`GET /health`：

- `ok=true`、`deployment_role=gpu-backend`
- `media_workers_enabled=true`
- worker services 包含 transcription、backfill、publish、enhance、creative、director、qianchuan、room-monitors
- `qianchuan_api_loaded=true`
- `qianchuan_pending=3602`、`qianchuan_running=0`、`qianchuan_done=0`
- `qianchuan_failed=7`、`qianchuan_permanent_fail=712`

`GET /api/status`：`active_recordings=1`、`total_recordings=9811`。  
`GET /api/monitor/status`：monitor running=true、5 个 room enabled/monitored、1 个 room recording；room 7 为 live/recording，当前 segment 为 `7_20260821_122340_000.mp4`，无 last_error。

### GPU worker 与 active tasks

`GET /api/gpu/status`：

- `reachable=true`、`online=true`、`gpu_online=true`
- health=`healthy`，CUDA available，设备为 RTX 4080 SUPER
- `gpu_busy=false`、`queue_depth=0`
- `clip_jobs_running=0`、`clip_jobs_pending=0`、`concat_jobs_active=0`
- transcription watchdog `active_tasks=0`
- `poll_state.active_job_id=null`、`last_poll_error=null`、`maintenance=false`
- ComfyUI `queue_running=0`、`queue_pending=0`

### 远端监听与进程

通过只读 SSH 查询远端监听：

```text
0.0.0.0:8899 LISTENING, OwningProcess=17336
0.0.0.0:8877 LISTENING, OwningProcess=2188
```

进程均为 `C:\Python313\python.exe` 的 `python` 进程，Responding=True。已确认：未发送 taskkill、停止、重启或启动命令。

## 8877 refused 与 8899 timeout 的根因判断

本次采集无法重现原始故障：两个端口均已恢复并连续完成本轮 GET。现有证据只能确认故障是瞬态/已恢复，不能把原始 `8877 connection refused` 归因到具体 Windows 服务、监听器或防火墙事件；本次只读日志检索没有取得可归因的历史日志 artifact。

`8899` 的部分 API timeout 也未在本轮重现。当前 `/api/groups` 能返回 HTTP 200，但响应体约 76 MB、包含 4321 个 group；这种大响应会放大客户端超时和传输压力，是一个已观察到的风险因素，但不足以证明它就是此前 timeout 的唯一根因。`/api/status` 与 `/api/monitor/status` 本轮均快速返回 200，说明当前 backend 主循环与核心只读状态接口可读。

下一步（仍不打断任务）：保留至少两个后续监测周期；若再次异常，在维护窗口由远端主机侧保存 Windows service/task、监听器、GPU/backend stdout/stderr 及系统事件日志，再进行根因归因。若没有 busy/active task 证据，不得恢复服务。

## 4675–4694 两批五版本只读验证

本轮分别对 `GET /api/groups` 结果进行了完整 ID 筛选，并对每个目标 ID 请求了只读 Qianchuan result 路由；结果如下：

- 当前 `/api/groups` 返回 4321 条，ID 范围为 1–4643，不包含 4675–4694 中任何一组。
- 对 4675–4694 的 `GET /api/v2/qianchuan/group/{id}/result` 均返回 `404 分组不存在`。
- 因而本轮无法从当前远端 API 读取这 20 组的 classic、director、realistic、conservative、Qianchuan 五版本状态；没有把“缺少记录”误判为视频失败，也没有触发生成或重试。
- 仓库已有 Issue 223 记录的历史只读结论：4675–4684 为缺失媒体类状态，4687 为商品强匹配不足，4685–4686 与 4688–4694 当时报告为 ready artifacts。该历史记录不能替代本轮线上证据，需待正确数据源/批次数据库恢复可读后重新只读核对。

## 安全边界与决定

- 未发送 POST/PATCH/DELETE 请求。
- 未暂停或停止 Qianchuan 队列。
- 未 retry、bulk generation 或重跑成功视频。
- 未强杀忙碌 GPU；当前 GPU 明确 idle，但 backend 有 active recording，故仍不执行恢复。
- 8877/8899 当前一致可达、health 可读、GPU queue/active tasks 为 0；维持现状比部署修复更安全。
