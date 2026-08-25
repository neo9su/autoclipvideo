# Issue #258 部署与 GPU 队列验收记录

**采集时间：** 2026-08-26 01:34（Asia/Shanghai）  
**目标：** `10.190.0.203` 生产 backend / GPU worker  
**结论：** 阻塞，未执行部署、重启、队列恢复或任何批量重试。

## 只读证据

证据原始输出见 [`docs/evidence/issue-258/readonly-diagnostics-20260826.txt`](evidence/issue-258/readonly-diagnostics-20260826.txt)。

- `8899 /health`: HTTP 200，运行版本仍为 `MVP1.04.2026032501`，不是本分支已合并的 `29bd896`。
- `8899 /api/gpu/status`: HTTP 200；GPU online，PID `13612`，GPU job 总数 `18602`，`queue_depth=0`，`pending_transcribe=11812`。
- 轮询状态仍停留在旧时间：`last_submit_at=2026-08-25T17:25:12.585176+00:00`，`last_poll_at=2026-08-25T17:34:13.768544+00:00`。
- `8877 /health`: HTTP 200，GPU worker healthy，PID `13612`，CUDA 可用，`queue_depth=0`。
- `8878 /health`: 本次请求无 HTTP 响应（HTTP 状态 `000`），watchdog 在 backend 状态中也显示 `reachable=false`。
- `/api/monitor/status`: backend 仍在运行，4 个房间受监控，其中房间 2 正在录制；因此不能执行未经授权的 backend 重启。

## 阻塞原因

对远端执行只读 SSH 连接时，认证被拒绝：

```text
Permission denied (publickey,password,keyboard-interactive)
```

因此无法安全确认：

1. backend 实际运行目录、当前代码 commit、启动方式和 canonical 服务管理器；
2. 数据库计数、GPU job 明细、磁盘空间/配额和备份位置；
3. 现有 PID 对应的启动命令及安全重启入口；
4. 部署 `29bd896`、重启 backend、验证 8878 watchdog；
5. 选择并提交一个代表性完整逻辑录音，完成转录并回写 SRT。

## 安全处理

- 未向生产写入文件或数据库。
- 未重启任何服务。
- 未调用恢复、重试、上传或批量处理接口。
- 未清理历史 chunk、源分片或完成产物。
- 未把 `11812` 个 pending 任务或历史 chunk 作为重试目标。

## 恢复前置条件

获得具备最小权限的远程运维访问后，应按以下顺序继续：

1. 记录运行目录、commit、PID/启动命令、数据库计数、GPU jobs 状态和磁盘空间；在同一运行目录创建带时间戳的配置/数据库备份。
2. 使用既有服务管理方式停止并启动单一 canonical backend，确认无重复进程；部署已合并的 `29bd896`，不覆盖配置和数据。
3. 连续验证 `8899`、`8877`、`8878`，并确认 backend health 版本/commit 已更新。
4. 先观察队列统计和轮询时间变化；只选择一个完整逻辑录音做端到端验收，禁止批量重试 pending 或历史 chunk。
5. 记录单个 GPU job id、转录完成状态、SRT 非空回写、数据库状态变化，并确认没有新增独立剪辑 chunk 任务。
6. 磁盘低于既有安全阈值时暂停恢复，不删除未验证媒体或完成产物。

在上述前置条件满足前，本 issue 应保持 **To Improve / blocked**，不能标记完成。
