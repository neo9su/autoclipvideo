# Issue 244 — 8899 backend 只读诊断报告

日期：2026-08-21（Asia/Shanghai）  
模式：只读诊断；未执行部署、重启、停止、kill、暂停、重试、生成或视频重跑。

## 结论

当前证据将故障分类为 **8899 backend 的进程/监听器级 outage**，不是主机整体不可达，也不像 8877 所在的网络路径故障：

- `10.190.0.203:8899`：连续 3 次 TCP `ConnectionRefusedError: [Errno 61] Connection refused`；`/health`、`/api/status`、`/api/stats`、`/api/groups` 均未取得 HTTP 响应。
- 同一主机 `10.190.0.203:8877`：TCP 连续 3 次连接成功，`/health` 返回 HTTP 200。
- 同一主机 SSH/22：TCP 连接成功。
- 因此主机、路由和基础网络路径至少在本次采样时可达；拒绝由 8899 端口本身或其前置监听器主动返回。仅凭外部探测不能区分 backend 进程退出、服务管理器未拉起、监听地址变化，或短暂 listener failure。
- 仓库历史 `backend.log` 有多次 `address already in use`，说明过去存在重复启动/端口竞争风险；该本地历史不能证明本次远端具体根因，但应纳入后续人工核验。

## 采样证据

### 2026-08-21 15:24 左右（Asia/Shanghai）独立探测

使用 Python 标准库 TCP connect 和 HTTP GET，避免依赖本机未安装的 `curl`/`nc`：

| 端点 | 结果 |
|---|---|
| `10.190.0.203:8899` TCP | 连续 3 次 `ConnectionRefusedError` |
| `10.190.0.203:8899/health` | 连接被拒绝 |
| `10.190.0.203:8899/api/status` | 连接被拒绝 |
| `10.190.0.203:8899/api/stats` | 连接被拒绝 |
| `10.190.0.203:8899/api/groups` | 连接被拒绝 |
| `10.190.0.203:8877` TCP | 连续 3 次连接成功 |
| `10.190.0.203:8877/health` | HTTP 200；RTX 4080 SUPER；`gpu_busy=false`；`queue_depth=0`；`active_tasks=0` |
| `10.190.0.203:22` TCP | 连接成功 |

仓库内只读诊断工具 `scripts/diagnose_remote_endpoints.py` 连续 3 个周期的结果一致：backend 8899 为 `connection_refused_or_reset`，GPU 8877 为 TCP/HTTP 可达。工具只执行 TCP connect 和 GET，不提交作业、不读取或修改队列、不执行恢复动作。

## GPU / Qianchuan 安全状态

- 本次没有发送任何会改变状态的请求。
- 8877 健康响应观察到：GPU healthy、`gpu_busy=false`、`queue_depth=0`、`active_tasks=0`；这是 GPU worker 在采样时的状态，不是 Qianchuan 全部任务的证明。
- 由于 8899 不可达，无法读取 backend 的 Qianchuan pending/running/done/failed 统计，也无法确认 backend active recordings。Qianchuan 状态应标记为 **未知**，不能因 GPU 空闲而暂停、重试、重跑或恢复调度。
- 已确认本次没有重启/停止 GPU 或 backend，没有 kill 进程，没有 flush 队列，没有暂停/停止/重试 Qianchuan，也没有重跑已完成视频。

## 安全恢复建议

1. 继续只读采样 8899、8877、SSH/22，记录时间、TCP 错误和 HTTP 状态；不要将连接拒绝自动转换为重试或重启动作。
2. 由具备主机权限的值班人员在不改变状态的前提下核验：8899 监听端口、backend 服务管理器状态、进程命令行/工作目录、最近启动日志和系统事件；同时确认 8877/GPU 进程及任务状态保持不变。
3. 在确认 Qianchuan 与录制任务无 active work、获得业务负责人明确批准前，不执行 backend 重启、部署、端口切换或服务拉起。若 active 状态无法证明，继续按“未知”处理。
4. 恢复后先做 8899 `/health`、`/api/status`、`/api/monitor/status` 的只读 GET，并要求连续 5 次成功、PID/启动时间稳定，再由人工决定是否恢复调度；随后单独确认 8877 `/health` 与 GPU 队列未被影响。
5. 若再次出现拒绝，优先保留主机侧服务管理器、监听器、backend stdout/stderr 和系统事件日志，再决定是否需要维护窗口内的恢复动作；不要先重启再取证。

## 后续代码/运维改进建议

本 issue 不直接修改生产代码或配置。若要修复，应另建实现 issue，范围至少包括：

- backend 监听器/服务管理器的单实例与端口冲突诊断；
- 启动失败时的明确告警和可审计日志；
- 只读健康检查区分“主机可达但端口未监听”和“应用 HTTP 失败”；
- 恢复策略必须带 active-task/Qianchuan 门禁，默认不自动重试或重跑；
- 回滚方式为撤销服务管理器/监控变更并恢复原启动命令，不触碰任务数据库和媒体。

本报告没有应用上述修复，也没有创建会自动恢复服务的调度器。
