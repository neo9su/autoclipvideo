# Issue #240 — 远端 Douyin 双端点只读可达性诊断

## 结论（2026-08-21 11:58 GMT+8）

- `10.190.0.203` 的本机路由存在（macOS `en1`），但 ICMP 连续 3 次均为 100% 丢包。
- `10.190.0.203:8899`（backend）和 `10.190.0.203:8877`（GPU）在 3 个连续采样周期内均不可达；TCP 错误在 `Host is down` 与 `Operation timed out` 间变化。
- 只读 HTTP GET（8899 `/health`、`/api/status`、`/api/monitor/status`；8877 `/health`、`/status`）均未收到 HTTP 响应，curl 返回连接失败。
- SSH 22 端口也报告 `Host is down`，因此当前证据更支持主机/网络路径级故障，而非仅某一个应用端口未监听。尚不能区分远端主机掉电、网卡/交换网络故障、ACL/防火墙丢弃或路径变化。
- 未执行任何重启、停止、强杀、队列 flush、Qianchuan 重试或视频重跑操作。

## 采样证据

| 周期 | 时间（GMT+8） | ICMP | 8899 TCP | 8877 TCP | SSH 22 |
|---|---|---|---|---|---|
| 1 | 11:58:28 | 无回包 | Host is down | Host is down | Host is down |
| 2 | 11:58:36 | 无回包 | Operation timed out | Operation timed out | Host is down |
| 3 | 11:58:47 | 无回包 | Host is down | Host is down | Host is down |

初始路由采样时间 11:58:04：目标经 `en1`，路由条目存在。初始 ping 为 3/3 超时；随后对 8899、8877、8878 的连接均失败。HTTP GET 未返回状态码。

## 当前复核（2026-08-21 12:08 GMT+8）

使用 `scripts/diagnose_remote_endpoints.py --host 10.190.0.203 --cycles 3 --interval 1 --timeout 1` 做了 3 个连续只读周期：

| 周期 | 时间（GMT+8） | 8899 TCP / HTTP | 8877 TCP / HTTP | 主机诊断 |
|---|---|---|---|---|
| 1 | 12:08:09 | `Host is down` / 无 HTTP 状态码 | `Host is down` / 无 HTTP 状态码 | `likely_host_or_network_failure`（high） |
| 2 | 12:08:10 | `Host is down` / 无 HTTP 状态码 | `Host is down` / 无 HTTP 状态码 | `likely_host_or_network_failure`（high） |
| 3 | 12:08:11 | `Host is down` / 无 HTTP 状态码 | `Host is down` / 无 HTTP 状态码 | `likely_host_or_network_failure`（high） |

本次 JSON 证据已写入本地临时文件供复核；未执行任何改变远端状态的动作。

可复现的诊断工具：`scripts/diagnose_remote_endpoints.py`。该工具只执行 TCP connect 和 HTTP GET，不读取或修改远端任务状态，不包含 ICMP、SSH、重启/停止/kill/队列操作。

## Qianchuan / GPU 运行状态判定

当前无法安全确认 Qianchuan 队列、GPU active tasks 或 4675–4694 的实时状态。端点不可达不等于队列为空、GPU 空闲或任务失败；远端进程可能仍在运行并持有任务，也可能在主机/网络故障期间中断。已有监控摘要显示此前曾出现 `Watchdog不可达` 和 pending 队列积压，但这只能作为历史背景，不能替代当前远端证据。

## 安全恢复建议与人工门槛

1. **先保持生产服务和队列不动。** 继续按固定间隔执行上述只读探测，记录 ICMP、8899、8877、SSH 的失败类型和时间；不要因不可达而自动重试、flush 或重跑。
2. **由具备网络/主机权限的人工值班人员核对基础设施。** 从同网段或管理平面确认 ARP/MAC、交换机端口、路由/ACL、防火墙、虚拟机/物理机电源与带外控制台；这些核对不应触碰应用进程。
3. **只有在主机恢复可达后再做应用级只读核验。** 依次 GET 8899 健康/监控接口、GET 8877 `/health`、GET 8878 `/status`，再通过远端主机只读查看进程、监听端口、服务日志尾部、GPU 进程/显存和任务数据库；禁止先重启来“验证”。
4. **恢复判定门槛：** 8899、8877、8878 连续 5 次健康检查成功，且 8899 的 GPU probe 为 fresh、PID/启动时间稳定，8877 报告队列/active 状态可读；确认后仍需人工判断是否允许恢复调度。
5. **忙碌任务保护：** 若只读证据显示 active task 或 GPU 进程仍在运行，不重启、不强杀、不暂停、不重试；等待任务自然完成或由业务负责人明确批准有边界的恢复动作。只有确认无 active task、无未落盘任务且取得人工批准，才讨论服务恢复。
6. **若无法证明任务状态：** 将状态标记为“未知”，冻结新增会改变队列的操作；保留现有数据库/日志证据，先由人工确认任务幂等性和恢复窗口。

## 本次变更

新增 `scripts/diagnose_remote_endpoints.py`，用于将上述安全的只读探测标准化并输出 JSON 证据；没有生产恢复副作用。
