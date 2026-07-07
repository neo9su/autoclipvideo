# demander.md — 抖音录屏流水线 需求 & 进度

> 最后更新: 2026-07-08 01:09 CST

## ✅ 2026-07-08 01:09 — 磁盘空间深度清理

### 问题
- 上次清理后磁盘仍有 209GB 根目录孤儿文件 + 其他缓存
- 需要全面扫描释放更多空间

### 清理结果
| 删除项 | 大小 | 说明 |
|--------|------|------|
| `voice_output/` | 22GB | 23779 个 wav，DB 无引用 |
| `gpu_storage/` | 55GB | 2058 文件，DB 无引用 |
| 根目录 orphan MP4 | 291GB | 1115 个文件，DB 完全不认识 |
| 根目录 orphan SRT | ~10MB | 2305 个文件，对应 MP4 已不存在 |
| DB 缺失文件标记 | 24 条 | DB 标记 active 但磁盘不存在的记录 |
| **合计** | **~369GB** | |

### 磁盘状态变化
| 阶段 | 使用率 | 可用空间 |
|------|--------|----------|
| 清理前 | 100% | 2.3GB |
| 第1轮（DB清理+merged删除） | 87% | 241GB |
| 第2轮（voice/gpu_storage/orphan MP4/SRT） | **67%** | **611GB** |

### recordings/ 最终分布
| 目录 | 大小 | 说明 |
|------|------|------|
| 小圆圆不圆/ | 415GB | 活跃直播间 |
| KUKU公主/ | 306GB | 活跃直播间 |
| 水卫士旗舰店/ | 22GB | 活跃直播间 |
| 根目录 active MP4+thumb | 209GB | 1697 个 active MP4 + 1258 个 thumb |
| unknown/ | 1.1GB | 未知房间 |
| 测试直播间/ | 98MB | 测试 |

### 当前 recordings 统计
| 指标 | 值 |
|------|-----|
| recordings 总数 | 4199 |
| recordings active | 1848 |
| recordings deleted | 2351 |
| clip_groups done (2,2) | 2227 |

---

## ✅ 2026-07-08 00:57 — 磁盘空间清理

### 问题
- 磁盘 100% 使用率，仅剩 2.3GB 可用
- recordings/ 目录 1.4TB，其中大量孤儿文件

### 清理结果
| 删除项 | 大小 | 说明 |
|--------|------|------|
| `recordings/director_outputs/` | 104GB | DB 无任何引用，孤儿输出 |
| `recordings/merged_*.mp4` | 135GB | 3336 个合并视频，DB 无任何引用 |
| `recordings/merged_*.srt` | 13MB | 对应 SRT |
| `recordings/merged_*_thumb*.jpg` | 12MB | 对应缩略图 |
| **合计** | **~239GB** | |

### 磁盘状态
- 清理前: 100% (2.3GB 可用)
- 清理后: **87% (241GB 可用)**

### recordings/ 当前分布
| 目录 | 大小 | 说明 |
|------|------|------|
| 小圆圆不圆/ | 415GB | 活跃直播间 |
| KUKU公主/ | 306GB | 活跃直播间 |
| 水卫士旗舰店/ | 22GB | 活跃直播间 |
| unknown/ | 1.1GB | 未知房间 |
| 测试直播间/ | 98MB | 测试 |
| SRT/Thumb 文件 | ~1GB | 关联 recordings 表 |

---

## ✅ 2026-07-07 04:02 — 数据库 & 文件系统清理

## ✅ 2026-07-07 04:02 — 数据库 & 文件系统清理

### 清理结果
- **recordings 表**: 6781 → 4199（减少 2582 条）
  - 删除 `transcribed=-1` 且 `size_bytes IS NULL` 的死记录: 3 条
  - 删除 `transcribed=0` 且 `size_bytes IS NULL` 的死记录: 1132 条（5-6 月未处理的孤儿记录）
  - 删除 `local_deleted=1` 且 `start_time < -90 days` 的过期记录: 1193 条
- **文件存在性检查**: 扫描 2090 条 active 录音的文件
  - 389 个文件缺失（3-5 月为主，18.6%）→ 标记为 `local_deleted=1`
  - 1701 个文件存在（81.4%）→ 保留 active
  - 最终 active: 2257 → 1868
- **clip_groups 表**: 4320 → 4320（结构不变，数据修复）
  - 修复 3 组不一致状态（director=-1, creative=2 → director=2）
  - 标记 85 组孤儿数据（director=0, creative=-1 → director=-1）
- **备份文件清理**: 删除 5 个 `.bak` 文件
- **空 DB 文件清理**: 删除 clip_jobs.db, douyin-recorder.db, douyin_recorder.db, recordings.db, transcription.db（均为 0 字节）
- **无用文件清理**: 删除 all, douyin, douyin.db.backup.*, backups/, backend/*.bak*, backend/*.sqlite3, backend/douyin_live.db, backend/jobs.db, backend/run.py, backend/run.sh, backend/.env.cf_blocked*
- **DB VACUUM**: 73MB → 62MB

### 当前状态
| 指标 | 值 |
|------|-----|
| recordings 总数 | 4199 |
| recordings active | 1868 |
| recordings deleted | 2331 |
| active: transcribed=-1 | 309（可重新转录） |
| active: transcribed=2, clipped=-1 | 279（可重新剪辑） |
| active: transcribed=2, clipped=2 | 1280（已完成） |
| clip_groups done (2,2) | 2227 |
| clip_groups director running | 2 |
| clip_groups creative running | 4 |
| clip_groups creative pending | 10 |
| clip_groups director failed | 1526 |
| clip_groups creative failed | 2079 |

### 待处理
- 366 个 transcribed=-1 的录音文件存在（>1MB），可尝试重新转录
- 478 个 transcribed=2 但 clipped=-1 的录音，可尝试重新进入剪辑流程

---

## ✅ 2026-07-05 11:50 — tqdm 日志污染修复

## ✅ 2026-07-05 11:50 — tqdm 日志污染修复

### 问题
- `backend/backend_run.log` 224MB, 788万行，其中 330万行是 tqdm "Batches: XX%" 输出
- tqdm 来自 GPU 服务的 CosyVoice2 TTS 和 Whisper transcribe，走 stdout
- `gpu_monitor.py` 把后端 stdout 重定向到 `backend_run.log`，导致 tqdm 污染主日志

### 修复
1. **GPU 服务层** — `gpu_service_src/gpu_service.py` + `gpu_service/main.py`
   - 新增 `_SuppressStdout` 上下文管理器，临时重定向 stdout/stderr 到 `/dev/null`
   - 在 `model.transcribe()` 和 `model.inference_*()` 调用周围包裹 suppressor
   - 不影响 logging（logging 走独立 handler，不受 stdout 重定向影响）
2. **日志清理**
   - 备份原始日志: `backend_run.log.bak.20260705`
   - 截断至最近 50000 行: 224MB → 2MB

### 部署
- `gpu_service_src/gpu_service.py` — 源码已更新 ✅
- `gpu_service/main.py` — GPU 服务器版本已同步 ✅
- **需要重启 GPU 服务**使 suppress 生效: `ssh 10.190.0.203 "systemctl restart gpu-tts"` 或通过 watchdog 自动重启

---

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

## ✅ 2026-07-05 11:28 — 死数据最终清理

### 清理结果
- **Director crashed (-2): 100 → 0** — 全部标记为 failed
  - 92 组 "no recordings in group"（录像已删除）
  - 8 组 "recording files missing"（物理文件丢失）
- **Director pending (0): 101 → 0** — 全部标记为 failed
  - 87 组 classic_status=2 但 recordings 不存在（room_id 查不到）
  - 7 组 classic_status=-2, 7 组 classic_status=0
- **Creative pending (0): 17 → 0** — 全部标记为 failed
  - 14 组 director 已失败（级联死数据）
  - 3 组 classic_status=-2（经典版也失败）
- **Classic pending: 10** — 保留（有有效 recordings，scheduler 可调度）

### 最终状态
| Pipeline | Done | Pending | Running | Failed | Crashed |
|----------|------|---------|---------|--------|---------|
| Director | 2760 | 0 | 4 | 1531 | 0 |
| Creative | 2210 | 0 | 4 | 2081 | 0 |
| Classic | 4092 | 10 | 0 | 1 | 192 |

> 所有 crashed (-2) 和 pending (0) 的 Director/Creative 组已清零。
> 剩余 10 Classic pending 是有有效录像的真实待处理组。

---

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

## ✅ 2026-07-05 01:53 — GPU 服务恢复 + 最新状态

### GPU 服务恢复
- **10.190.0.203:8877 GPU TTS 服务已恢复**（之前宕机约 1 小时）
- Watchdog (8878): GPU 和 ComfyUI 均 healthy
- ComfyUI (8188): 正常运行
- 本地后端通过 watchdog 检测到 GPU 在线，自动触发 backfill

### 当前统计（2026-07-05 01:53 CST）

#### Clip Groups Pipeline（2026-07-05 11:28 CST — 死数据清理后）
| Pipeline | Done | Pending | Running | Failed | Crashed |
|----------|------|---------|---------|--------|---------|
| Director | 2760 | **0** | 4 | **1531** | **0** |
| Creative | 2210 | **0** | 4 | **2081** | **0** |
| Classic | 4092 | 10 | 0 | 1 | 192 |

> ⚠️ **注意**: 仍有 111 Director crashed + 109 Creative crashed。
> 这些是 Phase 3 重试后再次失败的组（recoverable errors），不是死数据。
> Director crashed 主要是 "no recordings in group" (92组) — 这些应被排除在 Phase 3 重试之外。

#### Director 失败原因 TOP 5
1. `recording files missing (317)`: 669 组 — 录像文件物理丢失
2. `recording files missing (280)`: 385 组 — 同上
3. `无录像文件，跳过`: 121 组
4. `no recordings in group`: 121 组
5. `no SRT content available`: 14 组

#### Creative 失败原因 TOP 3
1. `director failed: recording files missing (317)`: 614 组 — 级联失败
2. `permanently_failed: duration 0.0s`: 412 组 — 时长不足
3. `director failed: recording files missing (280)`: 324 组 — 级联失败

### Backfill 运行状态
- Phase 2c: 每 5 分钟调度 7 个 director pending 组
- Phase 2d: 每 5 分钟调度 3 个 creative 组（director 已完成）
- Phase 3: 上次重置 6 个 director 组重试，之后无新的 recoverable 失败
- Phase 2 跳过 43 个 director 组 + 9 个 creative 组（文件缺失）

### tqdm 日志污染
- `backend_run.log` 中有 88,866+ 行 tqdm 进度条输出（Whisper/TTS 的 `Batches: XX%`）
- 这些输出写到了 stdout，与 Python logging 混合
- 日志文件 111MB，严重影响可读性
- **根因**: TTS/Whisper 的 tqdm 未重定向到独立流

### 可调度组
- **97 Director pending**: 大部分是 "recording files missing"（死数据），少数是可重试的
- **20 Creative pending**: 3 组 director done 可直接调度，其余需等 director 完成
- **4 Director running**: 正在处理中
- **3 Creative running**: 正在处理中

### 下一步
- [ ] GPU 服务已恢复，backfill 自动调度中
- [ ] 调查 Phase 3 重试后仍失败的组，确认是否应标记为 permanently_failed
- [ ] 清理 tqdm 日志污染（TTS stdout 重定向）
- [ ] 考虑将 "no recordings in group" 的 111 crashed 组也标记为 failed

---

## ✅ 2026-07-04 18:53 — 第二轮死数据清理 + GPU 服务宕机排查

### 清理结果
- 第二轮清理彻底清除了所有 crash 状态（-2, -3）:
  - Director: 2757 done, 69 pending, 4 processing, **1465 failed**, **0 crashed**
  - Creative: 2210 done, 17 pending, 1 processing, **2067 failed**, **0 crashed**
- 本次额外清理:
  - Creative -3 null error: 247 组 → failed（早期经典模式的孤儿数据）
  - Creative -3 video composition: 10 组 → failed
  - Creative -3 无合并素材: 2 组 → failed
  - Creative -3 自编版时长不足: 1 组 → failed
  - Creative -3 音频合并失败: 1 组 → failed
  - Director -3 无合并素材: 1 组 → failed
  - Director -3 null error: 1 组 → failed
  - Creative -2 no recordings: 10 组 → failed

### GPU 服务宕机
- **10.190.0.203:8877 GPU TTS 服务不可达**（连接拒绝）
- GPU 服务器本身可达（ping 正常），但 TTS/watchdog 服务均无响应
- ComfyUI (8188) 正常返回 HTML
- Watchdog (8878) 返回 404，SSH 登录失败（密钥认证问题）
- GPU watcher 自动尝试通过 watchdog 重启服务，但 watchdog 不可用
- **影响**: Director pipeline 在 segment matching 成功后会因 GPU compose 失败而报错
- **当前 4 个 processing Director 组大概率会失败**（GPU compose 3次重试后放弃）

### 可调度组
- Director pending eligible (classic_status=2): **53 组**
- Creative pending: **17 组**（全部 classic_status != 2，需手动处理）
- Scheduler 在 GPU 在线时会自动调度这些组

### 下一步
- [ ] 修复 GPU 服务器 10.190.0.203 上的 TTS 服务（SSH 密钥认证失败，需联系服务器管理员）
- [ ] GPU 恢复后 53 个 Director pending 组会自动被 scheduler 调度
- [ ] 17 个 Creative pending 组中部分 director_status!=2，需手动设置 classic_status=2 或修复 director 依赖
- [ ] 确认后端周期性调度日志是否正常输出（tqdm 日志污染严重）

## 待办
1. 🟡 评估将部分 TTS 作业路由到 222 (8878) GPU 服务以减轻 203 压力
2. 🟢 检查后端日志配置，`backend.log` 最后更新 6月23日但进程 6月25日仍在运行
3. ~~Phase 3 自动重试 crashed pipelines~~ ✅ 已完成（100 crashed + 101 pending 全部清理为 failed）
4. Classic pending 仅 10 组，scheduler 自动调度中
5. 🆕 GPU 监控脚本修复后需持续观察 24h 确认无虚假告警
6. ~~tqdm 日志污染~~ ✅ 已修复（`_SuppressStdout` + 日志截断 224MB→2MB）
7. 🎬 **镜头与场景变化增强**（Phase 1+2 全部完成）✅
   - [x] A2: 增强画中画触发条件（问题/对比/佩戴步骤/特写关键词）— `editor.py`
   - [x] A3: 运镜分配逻辑优化（开场→全景引入，产品→聚焦，步骤→跟随，对比→缩放）— `editor.py`
   - [x] B1: 导演版 camera_direction 字段注入 — `director_script.py` + `director_video.py`
   - [x] B2: 场景视觉区分增强（problem→冷/对比→分屏/detail→暖+PiP）— `director_video.py`
   - [x] C1: 智能镜头分割细化 — `editor.py` _split_long_segments() SRT/关键词双策略
   - [x] C2: 动态文字标注 — `director_video.py` 12种场景样式 + 高光增强动画
   - [x] C3: 对比场景分屏效果 — `gpu_service.py` hstack before/after + 自动标注

## ✅ 2026-06-29 09:25 — 发布页下载按钮 + 手动标记已发布

- **新增**: 发布任务详情页增加视频下载区域，按任务使用的版本显示对应下载按钮（经典版/导演版/自编版）
- **新增**: 非 done/publishing 状态的任务显示「手动标记已发布」按钮，点击后将任务状态设为 done 并记录时间戳
- **新增**: 数据库 `publish_tasks` 表新增 `manual_published` (INT) 和 `manual_published_at` (TEXT) 字段
- **新增**: 任务列表中手动标记的任务显示「手动」蓝色标签
- **新增**: 手动标记的任务详情显示「✓ 已手动发布」绿色提示和时间戳


## ✅ 2026-07-04 15:10 — 清理所有 crashed 死数据

### 问题
- Director crashed (-2): 1391 组 — 全部是 "recording files missing" 或 "no recordings in group"
- Creative crashed (-2): 535 组 — 525 组 "duration 0s"，10 组 "no recordings"
- 这些组的源录像文件已物理丢失或被标记 local_deleted=1，永远不会成功

### 修复
1. 将所有 Director/creative crashed (-2) 标记为 failed (-1)
2. 清理 pending (0) 中的死数据:
   - Director pending 130 组: "无录像文件/无合并素材/时长不足"
   - Creative pending 130 组: "无录像文件/无合并素材/无输出/空匹配"
3. 清理 creative 依赖死数据的级联:
   - 1039 Creative 组因 director 失败而卡住，标记为 failed
   - 1 Creative 组因 director crashed 而卡住，标记为 failed

### 最终状态
| Pipeline | Done | Pending | Failed | Crashed | Waiting | Total |
|----------|------|---------|--------|---------|---------|-------|
| Director | 2755 | 14 | 1524 | **0** | 2 | 4295 |
| Creative | 2208 | 17 | 1712 | **0** | 358 | 4295 |

### 可处理组
- **14 Director pending**: 有有效录像 (rooms 1&2)，需要 director scheduler 调度
- **3 Creative pending**: director_status=2，creative scheduler 可直接调度
- **其余 14 Creative pending**: director_status=0，需等 director 完成后才能调度

### 下一步
- 确认后端 scheduler 正常运行（每 5 分钟检查一次）
- 14 个 director pending 组应被自动调度处理
- 3 个 creative ready 组应被自动调度处理

