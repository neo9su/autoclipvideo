# 转录队列诊断部署与回滚说明

## 部署

1. 先在控制面执行 `bash scripts/qa.sh`，确认 lint、types、security、tests、coverage 五个门禁通过。
2. 发布后只读检查 `/api/gpu/status`：关注 `transcription_diagnostics.category_counts`、`ready_to_submit`、`no_submit_reason`、`samples`，以及 `poll_state.last_submit_at` / `last_complete_at`。
3. 用一个已完成、`duration_status=accepted` 且媒体存在的样本确认远端 GPU job 出现，并观察 `last_submit_at` 更新。该诊断不会修改数据库或切换本地执行。
4. 媒体/SRT 缺失样本应显示为终止/不可用分类；不要手工 reset 成功记录，也不要删除业务记录。

## 回滚

1. 回滚应用代码到上一版本即可；本变更不包含数据库 schema 迁移，因此不需要数据库回滚。
2. 回滚前后保留 `/api/gpu/status` 响应和服务日志作为审计证据。诊断字段消失不影响已有转录状态。
3. 若远端 GPU 不可用，保持 GPU-only policy，不启用本地转录或本地媒体 fallback；待远端恢复后再重试诊断。
