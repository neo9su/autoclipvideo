# GPU 服务管理端点

## 概述

为 GPU 服务添加了 HTTP 管理端点，允许通过 HTTP POST 触发服务重启，无需 SSH。

## 新增端点

### POST /admin/restart
重启 GPU 服务。

**请求参数:**
- 查询参数: `token=YOUR_TOKEN` (如果配置了认证)
- 请求头: `Authorization: Bearer YOUR_TOKEN` (如果配置了认证)

**示例:**
```bash
# 无认证
curl -X POST http://localhost:8877/admin/restart

# 使用 token 参数
curl -X POST 'http://localhost:8877/admin/restart?token=abc123'

# 使用 Authorization 头
curl -X POST http://localhost:8877/admin/restart -H 'Authorization: Bearer abc123'
```

**响应:**
```json
{
  "status": "restarting",
  "message": "Service will restart in 2 seconds"
}
```

### GET /admin/health
详细的健康检查，包含进程信息。

**响应:**
```json
{
  "pid": 12345,
  "started_at": 1234567890,
  "uptime_s": 3600,
  "auth_configured": true,
  "health": "healthy"
}
```

## 认证配置

设置 `ADMIN_RESTART_TOKEN` 环境变量启用认证：

```bash
# 在 GPU 服务器的 .env 文件中
ADMIN_RESTART_TOKEN=your_secure_token_here
GPU_API_TOKEN=your_gpu_api_token
```

## 自动健康检查

已创建 Windows 计划任务，每 5 分钟检查 GPU 服务状态并自动重启：

- 任务名称: `GPUHealthMonitor`
- 脚本: `check-gpu.bat` → `check-gpu.py`
- 频率: 每 5 分钟

## 部署步骤

### 方式一：使用部署脚本（推荐）

```bash
# 在 Mac 上运行
./scripts/deploy-gpu-admin.sh
```

### 方式二：手动部署

```bash
# 1. 复制 main.py 到 GPU 服务器
scp gpu_service/main.py neo@10.190.0.203:/tmp/

# 2. 在 GPU 服务器上部署
ssh neo@10.190.0.203 "cp /tmp/main.py C:\Users\neo\douyin_processor\main.py"

# 3. 创建 .env 文件
ssh neo@10.190.0.203 "echo 'ADMIN_RESTART_TOKEN=your_token' > C:\Users\neo\douyin_processor\.env"

# 4. 重启 GPU 服务
ssh neo@10.190.0.203 "taskkill /F /IM python.exe /FI 'IMAGENAME eq python.exe' && cd C:\Users\neo\douyin_processor && start /min C:\Python313\python.exe -m gpu_service.main"
```

## 快速恢复命令

```bash
# 无认证情况
curl -X POST http://localhost:8877/admin/restart

# 有认证情况
curl -X POST 'http://localhost:8877/admin/restart?token=YOUR_TOKEN'
```

## 监控脚本

`check-gpu.py` 会：
1. 定期检查 GPU 服务健康状态
2. 如果服务不可用，自动重启
3. 记录重启日志到 `restart.log`

## 注意事项

1. **重启延迟**: 服务会在 2 秒后重启，确保当前请求完成
2. **日志路径**: 重启后的日志输出到 `C:\Temp\gpu.out.log` 和 `C:\Temp\gpu.err.log`
3. **工作目录**: 新进程在工作目录 `C:\Users\neo\douyin_processor` 启动
4. **认证安全**: 建议在生产环境启用认证，使用强随机 token

## 故障排除

### 端点返回 404
- 确认 main.py 已正确部署
- 检查服务是否重启加载了新代码

### 端点返回 401
- 确认 token 配置正确
- 检查 Authorization 头格式

### 重启后服务未启动
- 检查 `C:\Temp\gpu.err.log` 获取错误信息
- 手动启动：`python -m gpu_service.main`
