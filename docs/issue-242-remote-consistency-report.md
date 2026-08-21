# Issue 242：远端 GPU worker 与 backend 一致性只读报告

日期：2026-08-21（Asia/Shanghai）  
模式：只读诊断；未执行部署、重启、停止、暂停、重试、生成或批量命令。

## 结论

本次复核时远端已自行恢复，未执行恢复动作：

- `10.190.0.203:8899`：TCP 可达；`/health`、`/api/status`、`/api/monitor/status`、`/api/gpu/status` 和 `/api/v2/qianchuan/status` 均 HTTP 200。
- `10.190.0.203:8877`：TCP 可达，`/health` HTTP 200。
- 诊断工具连续 5 个周期（2026-08-21 13:02:13–13:02:18，Asia/Shanghai）均报告 backend/GPU TCP 与 HTTP 可达，诊断为 `host_and_ports_reachable`，high confidence。
- 远端监听状态：`8899 -> PID 17336`，`8877 -> PID 2188`；两个进程均为 `python.exe` 且 `Responding=True`。
- backend 报告 `qianchuan_pending=3602`、`qianchuan_running=0`、`qianchuan_done=0`、`qianchuan_failed=7`、`qianchuan_permanent_fail=712`。
- GPU worker 报告 `queue_depth=0`、`gpu_busy=false`、`clip_jobs_running=0`、`clip_jobs_pending=0`、`concat_jobs_active=0`、transcription watchdog `active_tasks=0`；ComfyUI running/pending 也均为 0，`poll_state.active_job_id=null`、`last_poll_error=null`、`maintenance=false`。
- backend 当前有 2 个 active recordings（5 个 room enabled/monitored，2 个 recording），因此任何停止、重启或部署恢复均不满足安全门槛，本次明确不执行。

## 采集证据

### 端点探测

使用 `python3 scripts/diagnose_remote_endpoints.py --host 10.190.0.203 --cycles 5 --interval 1 --timeout 2` 做了 5 个连续只读周期。每个周期均为：

```text
backend 8899: tcp_reachable=true, http_reachable=true, HTTP 200 (/api/monitor/status)
gpu     8877: tcp_reachable=true, http_reachable=true, HTTP 200 (/health)
diagnosis: host_and_ports_reachable, confidence=high
```

补充 TCP 只读探测：`8899`、`8877`、`8878`、SSH `22` 均连接成功。`8877 /status` 返回 HTTP 404，未将不存在的路径误判为服务不可达；规范健康路径 `/health` 返回 200。

### backend 健康与队列

`GET /health`：

- `ok=true`、`deployment_role=gpu-backend`
- `media_workers_enabled=true`
- `qianchuan_api_loaded=true`
- Qianchuan pending/running/done/failed/permanent-fail 分别为 `3602/0/0/7/712`
- 服务版本为 `MVP1.04.2026032501`

`GET /api/status`：`active_recordings=2`、`total_recordings=9812`。  
`GET /api/monitor/status`：`running=true`、5 个 room enabled/monitored、2 个 room recording。

### GPU worker 与 active tasks

`GET /api/gpu/status`：

- `reachable=true`、`online=true`、`gpu_online=true`
- health=`healthy`，CUDA available，设备为 RTX 4080 SUPER
- `gpu_busy=false`、`queue_depth=0`
- `clip_jobs_running=0`、`clip_jobs_pending=0`、`concat_jobs_active=0`
- transcription watchdog `active_tasks=0`
- `poll_state.active_job_id=null`、`last_poll_error=null`、`maintenance=false`
- ComfyUI `queue_running=0`、`queue_pending=0`
- Qianchuan status endpoint：`qianchuan_available=true`、version `1.0.0`

### 远端监听与进程

通过只读 SSH 查询远端监听：

```text
0.0.0.0:8899 LISTENING, OwningProcess=17336
0.0.0.0:8877 LISTENING, OwningProcess=2188
```

两个进程均 `ProcessName=python`、`Responding=True`。已确认：未发送 taskkill、停止、重启或启动命令。

## 8877 refused 与 8899 timeout 的根因判断

本次采集无法重现原始 `8877 connection refused`：8877 已恢复监听，连续 5 个周期健康检查成功。现有证据只能确认故障是瞬态/已恢复，不能把原始 refused 归因到具体 Windows 服务、监听器或防火墙事件；本次未执行会改变远端状态的恢复操作，也没有取得足以归因的历史系统日志 artifact。

`8899` 的部分 API timeout 在本轮仍可解释为客户端超时敏感性：5 秒 `GET /api/groups` 未完成，但延长到 30 秒后成功读取 4321 条记录；`/health`、`/api/status`、`/api/monitor/status`、`/api/gpu/status` 和 Qianchuan status 均正常返回 200。该接口大响应会放大客户端超时和传输压力，是已观察到的风险因素，但不足以证明它是此前 timeout 的唯一根因。

因此当前最安全判定是：双端点已恢复一致可达，未达到需要部署修复的条件；保留后续只读监测。若再次异常，应在维护窗口由远端主机侧保存 Windows service/task、监听器、GPU/backend stdout/stderr 及系统事件日志，再进行根因归因。由于当前有 active recordings，任何服务重启或部署前仍需业务负责人明确批准并确认录制任务安全。

## 4675–4694 两批五版本只读验证

本轮对 `GET /api/groups` 结果进行了完整 ID 筛选，并对每个目标 ID 请求了只读 Qianchuan result 路由：

- 当前 `/api/groups` 返回 4321 条，目标 ID `4675–4694` 均不在结果中。
- 对 `4675–4694` 的 `GET /api/v2/qianchuan/group/{id}/result` 全部返回 HTTP 404（`分组不存在`）。
- 因而本轮无法从当前远端 API 读取这 20 组的 classic、director、realistic、conservative、Qianchuan 五版本状态；没有把“缺少记录”误判为视频失败，也没有触发生成、重试或重跑。
- 仓库已有 Issue 223 的历史只读结论不能替代本轮线上证据；需待正确数据源/批次数据库恢复可读后重新只读核对。

## 安全边界与决定

- 未发送 POST/PATCH/DELETE 请求。
- 未暂停或停止 Qianchuan 队列。
- 未 retry、bulk generation 或重跑成功视频。
- 未强杀忙碌 GPU；GPU 当前明确 idle，但 backend 有 2 个 active recordings，故仍不执行恢复。
- 8877/8899 当前一致可达、health 可读、GPU queue/active tasks 为 0；维持现状比部署修复更安全。
