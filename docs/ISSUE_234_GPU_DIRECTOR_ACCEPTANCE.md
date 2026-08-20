# 导演模式 GPU-only 端到端验收与回滚

## 验收样本

在生产环境选择一个 `recordings` 源 MP4 与非空 SRT 均可读、转录已完成、且 `clip_groups.director_status != 2` 的最小样本。验收只读查询数据库和媒体，不更新生产状态，也不重跑 `director_status = 2` 的成功视频。记录以下审计字段：`group_id`、`recording_id`、GPU job id、UTC 时间戳、部署版本/提交号；路径仅记录仓库相对路径或脱敏 artifact 名称。

## GPU-only 执行

1. 通过导演 API 生成脚本和配音，确认配音文件非空且可播放。
2. 调用 `compose-video`。控制平面只上传/下载媒体并轮询远程 GPU；本地媒体执行必须被 `RemoteGpuRequiredError` 拒绝。
3. GPU 服务必须收到非空 ASS 且至少包含一个带开始/结束时间的 `Dialogue` cue，以及非空 base64 TTS。缺任一项时 job 以 422 拒绝，不生成无字幕/无配音成片。
4. GPU 使用 NVENC 完成片段预处理、字幕烧录和音频编码。完成后控制平面先调用 `/director-jobs/{job_id}/quality`，通过后才下载并写入完成状态。

## 只读发布门禁证据

在 GPU 节点对最终 artifact 执行 `ffprobe -v error -show_streams -show_format -of json`，保存脱敏 JSON：必须存在一个视频流和一个音频流，时长大于 0，视频/音频时长差在发布策略允许范围内。用 GPU 节点的 `ffmpeg -ss <cue midpoint> -frames:v 1` 抽帧，确认字幕文字在画面中；用 `ffmpeg -af astats` 或等价只读检查确认音频可解码且存在非静音样本。配音源文件也必须单独通过 `ffprobe` 可读，并与最终视频音轨的采样率/声道配置一致。

记录“转录完成、SRT 非空/有效 timed cue、字幕视觉存在、配音可播放且已混入、最终视频可播放、时长/音轨门禁通过”六项结果；失败任一项不得标记 `director_status=2`。

## 部署与回滚

部署前先在 GPU 服务和控制平面分别记录当前版本号，先部署 GPU 服务，再部署控制平面；用一个未成功样本执行上述验收。失败时停止新导演任务，恢复上一个已验证的 GPU 服务镜像/提交和控制平面提交，重启服务，确认健康检查与 GPU-only policy 后再恢复队列。回滚不得把失败样本伪装为成功，也不得修改成功视频或生产数据库状态来制造验收证据。
