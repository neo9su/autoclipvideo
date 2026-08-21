# Issue #247 — 远端 GPU worker 8877 只读复测诊断

**采集时间：2026-08-21 17:51–17:53（Asia/Shanghai，GMT+8）**

## 安全边界

本次仅执行 TCP connect、HTTP `GET` 和现有只读 API 查询。未执行 SSH 成功登录、PowerShell、服务启动/停止、重启、强杀、队列 flush、Qianchuan retry、视频生成或视频重跑；未修改生产数据库、媒体文件或队列。

## 结论

- `10.190.0.203:8899` 正常可达，`GET /health`、`GET /api/gpu/status`、`GET /api/monitor/status` 均返回 HTTP 200。
- `10.190.0.203:8877` TCP 连接明确返回 `ECONNREFUSED`，`GET /health` 没有 HTTP 响应；这支持“8877 当前没有可接受连接的服务监听”或本机防火墙主动拒绝，不支持单纯网络不可达。由于 SSH 认证失败，不能进一步确认远端进程、监听表、Windows 服务状态或日志。
- 8899 到 8877 的应用探测为 `reachable=false`、`gpu_online=false`，`gpu_offline_seconds` 持续增长（复测期间约 29→65 秒）。这与 8877 的直接 connection refused 一致，不是单纯的状态误报。
- 当前没有安全、可授权的恢复动作：8877 进程/服务状态无法只读确认，且 Qianchuan 有运行任务与大量 pending。未重启或触碰队列。

## 端点、listener/process/service/log 证据

| 检查项 | 结果 |
|---|---|
| TCP `22` | 可达；SSH 使用非交互认证返回 `Permission denied`，无法读取远端主机状态 |
| TCP `8899` | 可达 |
| TCP `8877` | `Connection refused` |
| 8899 `/health` | HTTP 200；`deployment_role=gpu-backend`、`media_workers_enabled=true`、`qianchuan_api_loaded=true` |
| 8899 `/api/gpu/status` | HTTP 200；`reachable=false`、`gpu_online=false`、`maintenance=false`、`active_job_id=null`、`queue_running=0`、`queue_pending=0` |
| 8899 `/api/monitor/status` | HTTP 200；backend `running=true`，当前无直播录制，`pending_recordings=6313` |
| 8877 `/health` | 无 HTTP 响应；TCP connection refused |
| 8877 listener/process/service/log | **无法确认**：SSH 认证失败；不能将 TCP refused 等同于已证明的进程退出或 Windows 服务停止 |

8899 `/api/gpu/status` 的只读快照：

```json
{
  "reachable": false,
  "gpu_online": false,
  "gpu_offline_seconds": 65,
  "gpu_service_url": "http://10.190.0.203:8877",
  "comfyui": {"reachable": false, "queue_running": 0, "queue_pending": 0},
  "pending_transcribe": 6313,
  "poll_state": {
    "active_job_id": null,
    "poll_count": 2,
    "last_submit_at": null,
    "last_complete_at": null,
    "blocked_count": 0
  },
  "maintenance": false
}
```

## Qianchuan 与任务保护

复测期间只读 GET 观察到：

- `/health`：`qianchuan_pending=3592`、`qianchuan_running=3`、`qianchuan_failed=10`、`qianchuan_permanent_fail=716`、`qianchuan_probe_fail=0`。
- `/api/clip-queue`：`running=[]`、`queued=[]`、`total_queued=0`。
- 连续三次 `/api/gpu/status`：`pending_transcribe=6313` 不变；`active_job_id=null`；`gpu_online=false`；`gpu_offline_seconds` 从约 54 增至约 65 秒。8899 的 poll 状态在只读采样期间自行更新，但没有发送提交或恢复请求。

由于 Qianchuan `running=3` 且 pending 数量很大，任何重启、停止、强杀、retry、flush 或批量生成都可能影响活跃任务或队列，故全部未执行。`/api/gpu/status` 的 `active_job_id=null` 只代表该接口当前没有记录 active GPU poll job，不能推断 Qianchuan running 任务为空。

## 4675–4694 五版本可见性

- 对当前 8899 `/api/groups` 做完整只读读取：HTTP 200，返回 4321 个分组，当前 ID 范围为 `1–4643`；目标 `4675–4694` 全部不可见。
- 对 `GET /api/v2/qianchuan/group/{id}/result` 逐一读取 `4675–4694`：20 个请求均 HTTP 404，响应为“分组不存在”。
- 因此本轮无法从当前 backend 权威确认这 20 组的 classic、director、realistic、conservative、Qianchuan 五版本状态。历史文档不能替代当前线上证据。
- 没有触发任何目标组生成、retry 或重跑；已成功视频未被重复处理。

## 判定与恢复建议

**当前最可能判定：8877 服务端口未接受连接（服务停止/进程退出或服务未监听），但尚不能在“服务停止”和“主机防火墙主动拒绝”之间进一步区分。** 8899 与 SSH 端口可达，且 8877 是稳定 connection refused，因此“整台主机或网络路径故障”不是首选解释；也没有证据支持“仅 8899 状态误报”。

下一步仅建议由具备远端 Windows 管理权限的值班人员执行**不改变应用状态的**核对：

1. 查询 8877 的 TCP listener、PID、进程启动时间、Windows 服务/计划任务状态与服务日志尾部；
2. 确认 GPU worker 是否有未落盘任务或 Qianchuan active task；
3. 若确认无 active GPU/Qianchuan 任务、服务管理器有明确安全恢复路径并取得人工批准，才讨论单次最小服务启动/恢复；否则不重启、不强杀、不重跑；
4. 恢复后连续至少 5 次验证 8877 `/health`、8899 `/api/gpu/status` 与 Qianchuan queue，确认 PID/启动时间稳定后再由业务负责人决定是否恢复调度。

## 可复现的只读命令

```bash
python3 scripts/diagnose_remote_endpoints.py \
  --host 10.190.0.203 --cycles 3 --interval 1 --timeout 3

curl --connect-timeout 3 --max-time 8 \
  http://10.190.0.203:8899/health
curl --connect-timeout 3 --max-time 8 \
  http://10.190.0.203:8899/api/gpu/status
curl --connect-timeout 3 --max-time 8 \
  http://10.190.0.203:8899/api/monitor/status
curl --connect-timeout 3 --max-time 8 \
  http://10.190.0.203:8877/health
```
