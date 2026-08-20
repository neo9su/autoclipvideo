# Issue 234：GPU-only 导演成片验收与回滚

本文是可审计的最小验收记录模板。验收运行必须选择一个**未成功标记**的分组，
并在独立验收目录保存只读证据；不得修改生产数据库来制造成功状态，也不得重跑已经成功的
视频。

## 运行前检查

1. 记录部署版本（Git commit、GPU 服务版本）以及 UTC 时间戳。
2. 通过只读查询选择一个 `recording` 与 `clip_group`：源 MP4 可读、SRT 非空且至少包含一个
   有效 `start --> end` timed cue，转录已完成，且导演状态不是成功。
3. 记录 `group_id`、`recording_id`、`room_id`、文件名和转录状态。证据中不得出现凭据、令牌、
   环境变量值或主机敏感绝对路径。
4. 确认媒体执行节点为 `remote-gpu`。控制面只提交任务和下载产物；本地媒体执行必须失败。

## 验收证据

对源媒体、SRT、配音和最终 MP4 分别运行只读检查，并保存命令输出（脱敏后）：

```text
timestamp_utc: <填写>
deployment_version: <commit 或发布版本>
group_id: <填写>
recording_id: <填写>
room_id: <填写>
transcription_status: completed
source_mp4_readable: true
srt_non_empty: true
timed_cue_count: <大于 0>
execution_node: remote-gpu
gpu_job_id: <填写>
```

GPU 节点的 `/director-jobs/{job_id}/quality` 必须报告至少一个视频流和一个音频流，
且 `errors` 为空。使用 GPU 节点的 `ffprobe` 检查时长、编码、采样率，并使用 GPU 节点抽取
至少一帧字幕出现时间窗内的画面。帧证据应能确认字幕文字/区域确实存在；仅确认 ASS 文本存在
不算视觉验收。对配音单独检查可解码、非零时长，并与最终视频的音频时长在发布门禁容差内。

## 发布门禁

- 最终文件可被 GPU 节点 `ffprobe` 读取；视频流和音频流均存在。
- 最终时长与配音总时长一致（允许编码时间戳的小容差），并满足当前发布时长策略。
- 字幕烧录后的抽帧包含字幕视觉结果。
- 配音失败、配音文件缺失、字幕为空或字幕烧录失败时，任务必须为 error，不能写入成功状态。

## 部署与回滚

部署前先运行 `scripts/qa.sh`，确认五个门禁通过；部署控制面与 GPU 服务的同一版本，
然后只对上述未成功样本提交一次验收任务。若验收失败，保留 GPU job 日志和只读探测结果，
停止继续提交，不改写生产成功状态。回滚到上一已发布 commit/镜像并重启对应服务；确认
`remote-gpu` 策略仍生效，再用一个新的未成功样本复核。已成功视频不重跑。

