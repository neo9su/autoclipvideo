# Issue 235 转录队列诊断部署与回滚说明

## 部署前检查

1. 备份 `backend/transcribe.py`、`backend/main.py` 与 `backend/test_transcribe_queue.py`，保留文件权限和时间戳。
2. 先执行 `bash scripts/qa.sh`，确认 lint、types、security、tests、coverage 五个门禁通过。
3. 发布后只读检查 `GET /api/gpu/status`：确认 `transcription_queue.counts`、`samples`、`can_submit_count`、`blocked_reason` 与 `poll_state.last_submit_at`/`last_complete_at` 一致。
4. 对 `can_submit_count > 0` 的环境，观察远端 GPU 服务 job 创建及对应记录的 `synced`、`gpu_job_id` 变化；不要直接修改数据库或批量重跑。

诊断样本只返回 recording id、文件 basename、状态分类和必要的状态字段，不返回凭据或完整本地路径。分类包括 `ready_to_submit`、`duration_not_accepted`、`end_time_invalid`、`media_missing`、`srt_missing`、`merge_blocked`、`gpu_offline`、`gpu_error` 和 `gpu_job_running`。

## 回滚

停止后端调度后，从部署前备份恢复上述代码文件，重新执行 `bash scripts/qa.sh`，再启动后端并重复只读 GPU 状态检查。回滚不得 reset、删除或批量更新业务记录，也不得重跑已经成功完成的转录视频；远端 GPU 执行策略保持不变。
