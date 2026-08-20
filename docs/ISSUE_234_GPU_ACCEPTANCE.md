# Issue 234：GPU-only 导演成片验收

本文件是一次最小、可审计验收的操作记录模板。验收只读检查未成功样本，不重跑已经成功的成片，也不修改生产数据库状态。媒体生成必须使用 `remote-gpu`；控制端只允许提交任务、下载产物和执行 `ffprobe` 元数据检查。

## 样本选择

在部署控制端选择同时满足以下条件的单个样本，并记录 `group_id`、`recording_id`、部署版本和 UTC 时间戳：

```sql
SELECT g.id AS group_id, r.id AS recording_id, r.filename,
       r.srt_path, r.transcription_status, g.director_status
FROM clip_groups AS g
JOIN recordings AS r ON r.group_id = g.id
WHERE g.director_status != 2
  AND r.filename IS NOT NULL
  AND r.srt_path IS NOT NULL
  AND r.transcription_status IN ('done', 'completed', 2)
LIMIT 1;
```

确认 MP4 与 SRT 可读后，再执行导演脚本、GPU 配音和 GPU 合成流程。不得把凭据、环境变量值或主机绝对路径写入记录。

## 只读验收证据

记录以下命令的脱敏输出：

```bash
ffprobe -v error -show_entries format=duration:stream=codec_type,codec_name,channels,sample_rate \
  -of json <downloaded-final-video.mp4>
ffprobe -v error -show_entries format=duration:stream=codec_type,codec_name \
  -of json <generated-voiceover-audio>
```

证据必须证明：视频流存在、音频流存在且可解码、最终时长达到发布门禁、配音时长不为空，并且最终视频帧中能看到字幕。字幕视觉证据使用 GPU 产出的验收帧（或部署提供的等价只读帧检查），记录帧时间点和字幕文本；不能只用 ASS 文件存在代替视觉证据。

应用代码在写入 `director_status = 2` 前还会检查最终文件、配音文件、视频/音频流、有效 ASS `Dialogue` 事件和正时长。任一检查失败都进入错误状态，不会生成“无字幕”或“无配音”的成功成片。

## 部署与回滚

1. 部署控制端代码和 GPU 服务的同一版本，先执行 `bash scripts/qa.sh`，再确认 GPU 服务健康和 `execution_node=remote-gpu`。
2. 使用未成功样本运行一次验收；保存 group/recording、版本、时间戳、任务 ID、ffprobe JSON 和字幕验收帧索引。
3. 若验收失败，停止新导演合成任务，保留失败产物和日志供诊断；不要手工把状态改为成功。
4. 回滚控制端与 GPU 服务到上一已验证版本，恢复调度后重新检查健康状态。回滚不删除数据库记录、不覆盖已成功视频，也不启用本地媒体 fallback。
