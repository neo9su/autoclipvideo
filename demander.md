# demander.md — 抖音录屏流水线 需求 & 进度

> 最后更新: 2026-07-01 23:39 CST

## ✅ 2026-06-21 00:18-00:55 — LLM 迁移至 DeepSeek

- LLM 代理：`10.190.0.214:8080` → `https://api.deepseek.com`
- 模型：`deepseek-v4-flash`，API Key：`sk-4bf…8e8b`
- 修复：`response_format: {"type": "text"}`（关闭 reasoning）、max_tokens 400→1000
- 批量补分析：370 条成功，7 条 LLM 空响应失败，82 条 SRT 缺失
- 分析数：3201 → 3557

## 📊 当前统计（2026-06-22 02:05 CST）

### Classic Pipeline（recordings 表）
| 指标 | 数量 |
|------|------|
| 总录像 | 5503 |
| ✅ 已同步 | 4180 |
| ✅ 已分析 | 3557 |
| ⏳ analyzed=0（SRT 缺失） | 508 |
| ⏳ analyzed=-1（LLM 空响应） | 123 |

### Clip Groups Pipeline（2026-06-22 02:05 CST）
| 指标 | 数量 |
|------|------|
| 总组数 | 4118 |
| Classic done | 3920 |
| Classic pending | 10 |
| Classic running | 0 |
| Classic crashed (-2) | 187 |
| Director done (classic done 子集) | 2116 |
| Creative done (director done 子集) | 1480 |
| Director pending | 447 |
| Director running | 2 |
| Creative pending | 99 |
| Creative running | 2 |

### Director/Creative 状态细分（classic done 子集）
| 状态 | 含义 | Director | Creative |
|------|------|----------|----------|
| -3 | 等待中/未开始 | 968 | 227 |
| -2 | Crash/失败 | 261 | 288 |
| -1 | 错误 | 126 | 20 |
| 0 | Pending（backfill 处理中） | 447 | 99 |
| 1 | Running | 2 | 2 |
| 2 | Completed | 2116 | 1480 |

### Director/Creative 失败原因
- Director -2: 261（GPU 超时/无输出）
- Creative -2: 288（GPU 超时/无输出）
- Director -1: 126（错误，含 missing-file 跳过 69 组）
- Creative -1: 20
- 少量因时长不足、JSON 解析、SRT 缺失

## 🔄 Backfill 进度（持续运行中）
- 00:40 backfill 启动，修复 missing-file 验证逻辑
- 每轮调度 ~490-500 组（跳过 69 个 missing-file 组）
- 处理速度约 0.1-0.2 group/min（串行，受 GPU/转录排队影响）
- 02:02 状态：Director pending 447（从 1014 降了 567），Creative pending 99（从 455 降了 356）
- Director completed: 1971 → 2116（↑145），Creative completed: 1454 → 1480（↑26）
- 预计 Director pending 还需 45-90 小时完成
- GPU 服务空闲（3D=0%, queue=0），backfill 串行消费

## ✅ 2026-06-26 03:05 — Director Matcher Bug 修复

- **问题**: `_get_group_recordings()` SQL 未过滤 `local_deleted=1`，导致 535 条已删除录音被错误纳入 director 匹配，composition 阶段报 `video_clips is EMPTY`
- **修复**: `backend/director_matcher.py` 查询添加 `AND local_deleted = 0`，与项目其他查询保持一致
- **影响**: 修复后 director 匹配将只使用未被用户删除的录音，消除 535 条脏数据干扰

## ✅ 2026-07-01 23:39 — 项目文档保存 & GitHub 同步

### 📊 当前统计（2026-07-01 23:39 CST）

#### Classic Pipeline（recordings 表）
| 指标 | 数量 |
|------|------|
| 总录像 | 6365 |
| ✅ 转录完成 (transcribed=2) | 4482 |
| 🔄 转录中 (transcribed=1) | 7 |
| ✅ 已发布/已剪辑 (clipped=2) | 4467 |
| ❌ 转录失败 (transcribed=-1) | 732 |
| ⏳ 待上传 (transcribed=0, ready) | 0 |

#### Clip Groups Pipeline
| 指标 | 数量 |
|------|------|
| 总组数 | 4251 |
| ✅ Creative 完成 | 2131 |
| 🔄 Creative 运行中 | 0 |
| ⏳ Creative 等待 | 0 |

#### GPU 服务（10.190.0.203:8877）
| 指标 | 值 |
|------|-----|
| 状态 | ✅ 在线 |
| 队列深度 | ~7700-8000（持续增长） |
| gpu_busy | true |
| 3D 利用率 | 0%（whisper 使用 CUDA compute 而非 3D） |

### 🔧 重大修复

1. **GPU 监控脚本假空闲告警修复**（scripts/gpu_monitor.py）
   - **根因**: 空闲检测只看 `gpu_3d_pct`，whisper 转录使用 CUDA compute，3D 始终为 0%，导致每 5 分钟触发一次虚假告警
   - **修复**: 空闲判定改为 `gpu_3d < 20% AND NOT gpu_busy AND queue_depth < 100`，三者同时满足才判定空闲
   - **附带**: `fix_stuck_transcriptions()` 返回值 `total` → `checked`，避免误导

2. **Director/Creative 并发提升**（backend/transcribe.py）
   - `_DIRECTOR_SEM` 从 2 → 4
   - `_CREATIVE_SEM` 从 2 → 4
   - 目的：利用 RTX 4080S 16GB 余量加速流水线

3. **Pipeline 超时保护**（backend/transcribe.py）
   - Director pipeline 增加 30 分钟超时
   - 超时后自动重置状态，避免永久卡死

4. **启动时 pipeline 自动触发**（backend/main.py）
   - 后端启动时自动扫描 classic done 但 director/creative 未开始的组
   - 分批调度（batch=10），避免瞬间压满 GPU 队列
   - 跳过 director_status=1 和 creative_status=1 的卡死组

5. **Director pre-filter 增强**（backend/transcribe.py）
   - `_get_group_total_duration()`: 计算分组内有效录像总时长
   - `_check_group_recordings_exist()`: 验证录像文件是否存在
   - Director/Creative pipeline 启动前检查，跳过无效组

### 📝 文档更新
- `PROJECT_SUMMARY.md`: 新增 v1.5-v1.9 变更说明
- `MONITOR_LOG.md`: 新增 GPU 监控日志
- `demander.md`: 更新当前统计和待办
- `SHOT_VARIETY_EVAL.md`: 新增镜头与场景变化能力评估报告

## 待办
1. 🟡 评估将部分 TTS 作业路由到 222 (8878) GPU 服务以减轻 203 压力
2. 🟢 检查后端日志配置，`backend.log` 最后更新 6月23日但进程 6月25日仍在运行
3. Phase 3 自动重试 crashed pipelines
4. Classic pending 仅 10 组，几乎全部完成
5. 🆕 GPU 监控脚本修复后需持续观察 24h 确认无虚假告警
6. 🎬 **镜头与场景变化增强**（Phase 1 本周）
   - [ ] A2: 增强画中画触发条件（问题/对比/佩戴步骤/特写关键词）— `editor.py`
   - [ ] A3: 运镜分配逻辑优化（开场→全景引入，产品→聚焦，步骤→跟随，对比→缩放）— `editor.py`
   - [ ] B1: 导演版 camera_direction 字段注入 — `director_script.py` + `director_video.py`
   - [ ] B2: 场景视觉区分增强（problem→冷/对比→分屏/detail→暖+PiP）— `director_video.py`

## ✅ 2026-06-29 09:25 — 发布页下载按钮 + 手动标记已发布

- **新增**: 发布任务详情页增加视频下载区域，按任务使用的版本显示对应下载按钮（经典版/导演版/自编版）
- **新增**: 非 done/publishing 状态的任务显示「手动标记已发布」按钮，点击后将任务状态设为 done 并记录时间戳
- **新增**: 数据库 `publish_tasks` 表新增 `manual_published` (INT) 和 `manual_published_at` (TEXT) 字段
- **新增**: 任务列表中手动标记的任务显示「手动」蓝色标签
- **新增**: 手动标记的任务详情显示「✓ 已手动发布」绿色提示和时间戳
