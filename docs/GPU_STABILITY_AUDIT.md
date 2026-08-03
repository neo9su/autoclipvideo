# 小维 GPU 稳定性审计与回滚方案

## 计划任务清单与收敛方案

目标只保留一个入口：`DouyinGPUServices` → `start_all.bat`。该入口负责启动单一 watchdog，watchdog 配置负责单一 GPU worker 和单一 ComfyUI。`GPUService`、`DouyinGPUServices_Boot`、`StartGPUSvc` 是待审计重复任务；禁止直接删除，先运行 `gpu_service/install_canonical_autostart.bat` 导出 XML 到备份目录并禁用它们。

回滚：在确认原因后，用备份 XML 通过任务计划程序导入，并按原任务名重新启用；回滚前先停止 canonical 任务，避免竞态。每次变更后检查 8877、8878、8188 和后端 `/api/gpu/status`。

## 日志与重启原因调查

`backend/watchdog_agent.py` 已将 watchdog 日志改为 20 MiB 单文件、保留 5 个轮转文件。远端审计只能使用 `scripts/gpu_stability_audit.py` 的尾部读取；不允许 PowerShell `Get-Content` 全量扫描大文件。最近重启原因应从 watchdog 尾部、服务退出码、启动时间和健康探测时间线交叉判断；若没有退出码/日志证据，报告为“原因未证实”，不能臆测。

## Whisper 审计

对 PID 18396 先记录命令行、作业 ID、输入路径、队列条目和 CPU 时间。存在合法作业证据则保留并观察；没有证据则标记人工复核。审计工具不会杀进程。

## 服务状态字段

watchdog `/status` 记录 PID、端口由服务配置固定、启动时间、运行时长、重启次数、最后退出码和健康状态。后端通过 worker 直接探测，避免只依赖旧 watcher 状态。

## 恢复测试

1. 在 Windows GPU 主机执行 canonical 安装脚本并保留 XML 备份。
2. 检查任务列表只有 canonical 入口处于启用状态。
3. 连续 3 次、间隔至少 10 秒请求 8877/8878/8188 与 8899 `/api/gpu/status`。
4. 重启后重复检查；GPU 故障时确认队列等待，不能在 macOS 启动 worker。
5. 保留输出作为部署审计记录。
