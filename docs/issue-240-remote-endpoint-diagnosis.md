# Issue 240：远端双端点只读诊断

## 目的

`10.190.0.203:8899`（backend）与 `10.190.0.203:8877`（GPU）同时出现
`Host is down` 或 `connection refused` 时，使用
`scripts/diagnose_remote_endpoints.py` 采集可复核证据。工具只建立 TCP
连接并发送 GET 请求，不会重启/停止服务、提交或重试 Qianchuan、清理队列，
也不会重跑已成功视频。

## 使用

单次快照：

```bash
python scripts/diagnose_remote_endpoints.py --host 10.190.0.203
```

连续多个监控周期并保存 JSON 证据（示例为 3 个周期、每周期间隔 5 分钟）：

```bash
python scripts/diagnose_remote_endpoints.py --cycles 3 --interval 300 --output remote-endpoint-evidence.json
```

每个端点记录 UTC 时间、TCP 是否可达、TCP 失败分类、HTTP 状态/失败分类。
默认只读取 backend `/api/monitor/status` 与 GPU `/health`；HTTP 4xx 仍表示
端口和 HTTP 服务可达，5xx 则单独标为应用服务错误。

## 判定边界

| 证据 | 结论 | 下一步（仍不打断任务） |
| --- | --- | --- |
| 两端 TCP 都是 `host_or_network_down` | 高度怀疑主机掉线、路由/交换网络或主机防火墙 | 由网络/主机管理员核对 ARP、交换端口、路由、云/宿主机电源与带外控制台；不先重启服务 |
| 两端 TCP 都是 `connection_refused_or_reset` | 主机可达，但两个监听服务未接受连接或被主动拒绝 | 在维护窗口由人工只读核对监听端口、服务管理器和日志；先冻结新提交，不触碰运行中任务 |
| TCP 成功但 HTTP 5xx/超时 | 网络路径可用，服务进程或应用依赖异常 | 先保存服务日志、队列快照和 GPU 状态；只有人工确认无 busy/active task 后才讨论恢复 |
| 一个端点成功、另一个失败 | 不是足够证据证明整机故障 | 分别处理端口/服务，保持可达端点和现有队列不变 |

## Qianchuan/GPU 运行状态的安全解释

端口不可达**不能证明** Qianchuan 队列或 GPU active tasks 已停止：进程可能
仍在运行但网络、监听器或防火墙异常。因此在恢复决策前，应由目标主机本地或
带外只读采集：服务进程/监听状态、Qianchuan 队列摘要、GPU active task、
最近日志时间戳和任务 ID。若无法取得这些证据，按“状态未知”处理，不得重试、
强杀 GPU 或重跑成功视频。

## 人工恢复门槛

只有同时满足以下条件，才可由值班人员批准恢复动作：

1. 已保存至少两个连续周期的端口/HTTP 证据及失败时间；
2. 已确认是网络/主机故障还是单服务故障；
3. 已确认 Qianchuan 队列为空或已持久化，且 GPU 无 active/busy task；
4. 已明确恢复动作、回滚方式和任务不重复执行的保护；
5. 生产负责人明确批准。若第 3 项无法确认，继续只读诊断并等待人工决定。
