# 发布视频 300 秒门禁变更

## 变更范围

- `backend/publish_policy.py` 是发布时长的唯一策略来源：15 秒（含）至 300 秒（含）。
- `backend/publish_scheduler.py` 在所有自动发布任务进入发布器前使用该策略；原视频路径、GPU-only media policy 和其它质量检查不变。
- `tests/test_publish_duration_gate.py` 覆盖旧门禁以上、300 秒以内的 150.1 秒、162.8 秒和 300 秒边界。

## 部署前备份

在远端部署前，将当前版本的 `backend/publish_policy.py`、`backend/publish_scheduler.py`、前端构建产物及数据库备份到带时间戳的发布备份目录。不要覆盖源视频；重新剪辑输出应写入新的文件名，并在校验通过后再更新对应任务引用。

## 验证

1. 运行 `bash scripts/qa.sh`，确认五个门禁均通过。
2. 对目标文件运行 `ffprobe`，确认视频流存在、分辨率满足现有要求、时长 `<= 300.0` 秒。
3. 调用发布队列质量检查，确认返回 `passed=True`；再仅重试目标发布任务，观察队列状态。
4. 检查源视频哈希未变化，检查无关任务的状态和 `clip_groups` 记录未变化。

## 回滚

停止发布 worker，恢复部署前备份的代码和前端产物，再启动 worker 并运行同一组验证。回滚不删除源视频、不重跑其它视频；如需恢复目标任务引用，仅恢复该任务在部署前的 `video_path` 快照。
