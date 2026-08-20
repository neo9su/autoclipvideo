# Issue 234：GPU-only 导演成片验收

## 验收范围

本验收只选择一个 `classic_status=2`、`director_status=0` 且源 MP4 与非空 SRT 均可读的最小样本；不重跑任何 `director_status=2` 的成片，也不直接修改生产数据库状态。记录 group/recording 标识、UTC 时间戳、部署版本、远端 GPU job id 和只读探测结果时，禁止写入凭据、令牌或主机绝对路径。

## GPU-only 验收步骤

1. 在控制面只读查询候选 group、recording、MP4/SRT 可读性、转录完成状态和有效 timed cue；确认目标尚未成功。
2. 记录部署版本和远端 GPU 节点，触发导演流程。所有媒体处理必须通过 `director-jobs`；控制面不得运行本地 ffmpeg/ffprobe。
3. 等待 job `done`，记录 job id、提交/完成时间和返回的质量报告。
4. 在 GPU 节点用 `ffprobe -show_streams -show_format` 和 decode smoke 检查最终文件：必须存在视频流、音频流，时长满足发布门禁，且音频可解码。
5. 通过 GPU 节点帧截图或等价只读视觉检查确认 timed cue 的文字在最终视频中出现；同时确认远端质量报告的 `subtitle_burned=true`、`voiceover_mixed=true`。原始配音文件单独用 GPU 节点解码检查，并与最终文件的音轨存在性关联。
6. 保存脱敏验收记录（group/recording、时间戳、版本、job id、时长、流数量、字幕 cue/帧时间点、音频检查结果）。不得把凭据、令牌或主机敏感路径写入 issue/PR。

验收失败必须保持 `director_status != 2`，并记录可重试的错误；不能用数据库写入伪造成功证据。

## 失败门禁

GPU worker 在进入最终编码前拒绝以下输入：

- ASS 缺失或不含 timed `Dialogue:` cue：拒绝生成无字幕成片；
- 配音 base64 缺失、解码为空：拒绝生成无配音成片。

质量端点还要求最终 job 同时记录 `subtitle_burned` 与 `voiceover_mixed`，否则质量门禁失败。API 只有在远端质量门禁通过后才将状态写为完成。

## 部署与回滚

### 部署

1. 先在 GPU 节点部署 worker，并确认服务健康、NVENC/ASS 字体和媒体挂载可用。
2. 部署控制面代码，逐步观察单个未成功样本的 job、远端质量报告和状态转换。
3. 仅在上述只读证据齐全后扩大到后续未成功样本；不触碰已成功视频。

### 回滚

1. 停止新任务调度，保留已生成的 GPU job 日志与脱敏质量报告。
2. 回滚控制面与 GPU worker 到上一已验证版本；不要删除源媒体、SRT、job 输出或验收记录。
3. 检查运行中的 job，失败任务保持非完成状态；已成功且有完整证据的输出不回滚、不重跑。
4. 恢复调度前重新执行一个未成功样本的 GPU-only 验收，确认字幕和配音失败门禁仍生效。
