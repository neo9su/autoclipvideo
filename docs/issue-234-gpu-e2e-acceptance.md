# Issue 234：GPU-only 字幕与配音端到端验收

## 验收执行记录

本文件是可审计记录模板。执行时只填写业务 `group_id`、`recording_id`、GPU job id、UTC 时间戳和部署版本；不要填写凭据、环境变量值或控制机/服务器绝对路径。不得为验收重跑 `director_status=2` 的成功视频，也不得直接修改生产数据库状态。

| 项目 | 记录 |
| --- | --- |
| group / recording | `<group_id>` / `<recording_id>` |
| 源 MP4 与 SRT | `ffprobe` 可读；SRT 非空，至少一个有效 timed cue |
| 转录状态 | `transcription_status=2`（只读查询） |
| GPU execution | `execution_node=remote-gpu`；控制面未执行本地 ffmpeg/ffprobe |
| GPU job / 时间戳 | `<job_id>` / `<UTC timestamp>` |
| 部署版本 | `<git sha or image tag>` |
| 质量证据 | `/director-jobs/<job_id>/quality` 返回视频流、音频流、正时长、`subtitle_burned=true`、`generated_voiceover_mixed=true` |
| 视觉证据 | GPU 节点抽帧检查字幕可见；记录抽帧时间点与人工/视觉检查结果 |

发布门禁：远端质量接口必须同时报告视频流、音频流和正时长；ASS 必须包含 timed `Dialogue:`；配音 payload 必须非空且最终音频流存在。任一条件失败，job 进入 error，导演状态不得进入完成（`director_status=2`）。

## 部署

1. 在发布窗口前部署控制面和 GPU worker 的同一版本，确认 worker 已加载 ASS 字体并可访问源媒体存储。
2. 通过现有导演接口选择一个源 MP4、非空 SRT、且未成功标记的最小样本；仅创建 GPU job，不改写成功记录。
3. 轮询 job 状态为 `done`，再读取 `/quality`，保存脱敏 JSON、时间戳和版本号；使用 GPU 节点视频帧检查字幕，并确认配音 WAV 可播放且成片音轨存在。
4. 只有质量证据齐全后，才允许现有后台流程写入完成状态。

## 回滚

停止新版本的导演任务调度，恢复上一个已验证的控制面和 GPU worker 版本；保留失败 job 的错误和脱敏质量证据，不把失败产物标记为完成。恢复后先用未成功的验收样本重试，确认字幕/音频门禁仍 fail-closed，再恢复正常调度。
