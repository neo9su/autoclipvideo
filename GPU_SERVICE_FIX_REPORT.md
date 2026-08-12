# GPU服务稳定性修复报告

## 问题诊断

### 根因分析
1. **SSH隧道依赖** - GPU服务通过SSH隧道运行，SSH断开即导致服务挂掉
2. **Windows计划任务不可靠** - 原`\GPU_Service`任务限制为"登录时运行"且仅交互式模式
3. **WatchdogAgent已禁用** - 状态为Disabled，无法自动恢复
4. **前端代理配置错误** - vite.config.js默认指向`10.190.0.203:8899`而非`localhost:8899`

### 历史数据
- 590次GPU探测错误（backend.log）
- 42次"service restarted"错误（2026-07-19）
- 多次Connection refused/reset错误

## 已实施的修复

### 1. SSH隧道管理优化
- 创建launchd服务 `com.claw.gpu-tunnel` 管理SSH连接
- 配置Keepalive: `ServerAliveInterval=30`, `ServerAliveCountMax=3`
- 启用`ExitOnForwardFailure`确保隧道故障时立即感知
- 停止旧的SSH隧道进程（PID 22497）

### 2. Windows服务配置
- 创建Windows服务 `DouyinGPUService`
- 启动脚本: `C:\Users\neo\douyin_processor\gpu_service\win_gpu_service.bat`
- 配置为自动启动（`start= auto`）
- 设置30分钟超时保护

### 3. 前端代理修复
- 更新 `vite.config.js` proxy配置
- 默认指向 `localhost:8899` 而非 `10.190.0.203:8899`
- 重启frontend launchd服务

### 4. SSH配置优化
- 添加Host 10.190.0.203配置段
- 启用TCPKeepAlive和ServerAliveInterval

## 当前状态

### 运行中服务
| 服务 | 状态 | 端口 | 管理方式 |
|------|------|------|----------|
| Mac Backend | ✓ 运行 | 8899 | launchd (com.claw.douyin-gpu-service) |
| Frontend | ✓ 运行 | 5173 | launchd (com.claw.douyin-frontend) |
| SSH隧道 | ✓ 运行 | - | launchd (com.claw.gpu-tunnel) |
| GPU服务 (Windows) | ✓ 运行 | 8877 | SSH隧道 + Windows服务 |
| WatchdogAgent | ⚠ 禁用 | 8878 | 待启用 |

### API验证
- `http://localhost:8899/api/gpu/status` ✓ 可达
- `http://localhost:5173/api/gpu/status` ✓ 代理正常
- GPU服务状态: `reachable=True, gpu_online=True`

## 后续建议

1. **启用WatchdogAgent** - 在Windows上手动启动watchdog服务
2. **监控SSH隧道** - 定期检查`/tmp/gpu_tunnel.log`
3. **配置日志轮转** - 避免日志文件过大
4. **添加健康检查告警** - 当GPU离线时发送通知

## 故障排除

### 检查服务状态
```bash
# 查看launchd服务
launchctl list | grep douyin
launchctl list | grep gpu-tunnel

# 查看GPU服务状态
curl http://localhost:8899/api/gpu/status

# 查看SSH隧道日志
tail -f /tmp/gpu_tunnel.log
```

### 重启服务
```bash
# 重启SSH隧道
launchctl stop com.claw.gpu-tunnel
launchctl start com.claw.gpu-tunnel

# 重启Backend
launchctl stop com.claw.douyin-gpu-service
launchctl start com.claw.douyin-gpu-service
```
