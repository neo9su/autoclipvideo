# demander.md — 抖音录屏流水线 需求 & 进度

> 最后更新: 2026-07-09 20:13 CST

## ✅ 2026-07-09 20:13 — 成片最终后处理：4K / 50fps / 背景补齐

### 需求
在剪辑完成的最后增加一道统一后处理工序：将最终短视频补分辨率到竖屏 4K、补帧率到 50fps，并对非 9:16 画面做背景补齐。

### 已执行
1. 新增 `backend/final_video.py`，提供统一 `postprocess_final_video(...)`：
   - 输出画布固定为竖屏 4K：`2160x3840`。
   - 输出帧率固定为 `50fps`。
   - 视频主体等比缩放居中。
   - 背景层使用原画面等比铺满、裁切、强模糊、轻微调暗/增饱和，解决横屏/非 9:16 素材黑边或空白边问题。
   - 音频统一转 AAC 160k / 48k，并保留 `+faststart`。
2. 接入导演模式自动流水线：`backend/transcribe.py` 的 `director_final_video` 写库前，先完成 28s/30.5s 时长兜底，再执行 4K/50fps/背景补齐。
3. 接入自编/创意模式自动流水线：`creative_final_video` 写库前执行同一后处理。
4. 接入手动/API 导演合成路径：`backend/api_v2.py` 在写入 `director_final_video` 前执行同一后处理，保证前端手动生成和后台自动生成一致。
5. 接入经典剪辑合并路径：`backend/analyzer.py` 新增 `_finalize_classic_merge(...)`，三条经典合并路径（GPU classic-concat、GPU stream-copy concat、本地 ffmpeg concat）完成后统一进入 4K/50fps/背景补齐，再写入 `merged_filename`。
6. 后处理失败时不静默降级：对应任务标记失败，避免发布不符合规格的视频。

### 验证
- `python3 -m py_compile backend/final_video.py backend/transcribe.py backend/analyzer.py backend/api_v2.py` ✅
- ffmpeg 合成 640x360/25fps 测试视频后执行 `postprocess_final_video(...)`，ffprobe 输出：`2160,3840,50/1` ✅
- 待执行：`git diff --check`、提交并推送。

---

## ✅ 2026-07-09 11:15 — 导演剪辑逻辑增强：多场景、多镜头、细节强调

### 已执行
1. 调整 `backend/director_video.py` 导演合成层，不再只依赖 LLM 返回的镜头建议；合成前会根据 `scene_type` 自动补齐 `camera_direction` 和 `transition_type`。
2. 增加场景默认剪辑动作：
   - hook：拉远/快速推进，强化前三秒停留。
   - problem/comparison：推进或强推进，突出痛点与对比差异。
   - detail/product/wearing/demonstration：推进、强推进、左右平移，强调发丝、网底、佩戴步骤。
   - result/scene/cta：拉远展示整体效果并收尾。
3. 增加多镜头拆分：对 `detail/product/wearing/demonstration/comparison` 等细节/操作类长片段，7 秒以上自动拆成 2 个镜头，12 秒以上拆成 3 个镜头；后续镜头微调起点形成跳切，避免同一素材长时间静态播放。
4. 字幕同步适配多镜头：拆分后的第一镜头承载完整字幕时间轴，后续镜头只做画面切换，避免重复字幕或字幕时间漂移。
5. GPU payload 增加 `shot_index/shot_count`，并保留每个片段的 `scene_type/camera_direction/transition_type`，方便 GPU 侧按镜头信息做差异化处理；本地 ffmpeg fallback 已直接使用这些字段生成 zoompan/转场效果。
6. 更新 `backend/api_v2.py` Director status 版本号到 `2.0.1`，与 README/frontend 版本一致。

### 对抖音要求的剪辑动作说明
- **多场景切换**：脚本仍按 hook、痛点、细节、佩戴、效果、CTA 等 `scene_type` 组织；合成层按场景套不同调色、字幕样式、节奏和转场，形成明确段落感。
- **多镜头切换**：产品细节/佩戴演示/对比场景不再是一段长镜头，自动拆为 2-3 个短镜头，并通过轻微错位取材、slide/xfade/dissolve/fade 等转场制造跳切节奏。
- **细节强调**：detail/product/comparison 场景默认强推进或推进，wearing/demonstration 场景默认左右平移跟随动作；关键词字幕继续高亮发丝、网底、佩戴步骤、固定方式等核心词。

### 验证
- 待执行：`python3 -m py_compile backend/director_video.py backend/api_v2.py`
- `git diff --check` ✅

---

## ✅ 2026-07-09 00:10 — 后端恢复、tqdm 本地污染修复、剪辑逻辑审计

### 已执行
1. 启动后端 FastAPI:8899，恢复监控/转录/剪辑/发布调度。
2. 检查 GPU 服务：10.190.0.203:8877 正常，queue=0；watchdog 8878 正常。
3. 排查日志污染：GPU 服务侧 `_SuppressStdout` 已存在，但本地 `sentence_transformers.encode()` 仍输出 tqdm `Batches:`。
4. 修复 `backend/director_matcher.py`：所有本地 `SentenceTransformer.encode()` 增加 `show_progress_bar=False`。
5. 重启后端验证：新日志 `Batches:` 计数为 0，`py_compile backend/director_matcher.py` 通过，`git diff --check` 通过。

### 发现的问题 / 未完成任务
1. **发布任务失败**：抖音发布 cookie 失效，日志反复出现 `Cookie 失效`、`upload area not found`、`Locator.wait_for timeout`。需要重新扫码登录或刷新发布账号 cookie。
2. **老数据 SRT 大量缺失**：活跃且 `transcribed=2` 的历史录音中，仅近期 7/8 之后部分 SRT 文件仍在；旧 SRT 大量缺失，导致 Director backfill 中 4 组报 `no SRT content available`。这些组不适合继续重试，应标记永久失败或重新转录。
3. **少量剪辑低于 30 秒**：Creative group 4655 生成视频 29.2s，被 30s 最低时长保护拒绝。需要调整补时/片段选择，或降低最低时长阈值。
4. **GPU 服务重启接口不可用**：`/admin/restart` 与 watchdog `/restart` 返回 404，SSH 失败；如果要让 GPU 侧 suppress 生效，需要服务器管理员重启服务。

### 当前剪辑逻辑总结
- Classic：录音转写完成后按 SRT 智能选段，使用音频/视觉/语义/LLM 评分，支持长段拆分、动态字幕、转场、运镜、缩放、PiP 等效果；输出写回 `recordings.clip_filename` / `clipped=2`。
- Director：基于分组 SRT + 商品信息生成 7-8 段导演脚本，匹配原始录像片段，按房间 voice clone 合成旁白，GPU 合成最终视频；带文件存在性、SRT、30min 超时、最终时长 >=30s 校验。
- Creative：不依赖 SRT 文案生成，按商品信息生成自编卖点脚本；仍依赖原始录像做画面匹配和 GPU 合成；同样有总素材时长、30min 超时、最终时长 >=30s 校验。
- 场景增强：导演/自编版支持 scene_type 驱动的视觉区分、动态文字标注、特写/细节 PiP、对比场景分屏、camera_direction 运镜字段注入。

### 建议下一步
1. 优先刷新抖音发布 cookie，避免 490+ failed publish 继续堆积。
2. 对 `no SRT content available` 的历史 Director 组做一次性永久失败标记，避免每次后端启动重复调度。
3. 修复 Creative 29.x 秒边界：合成阶段自动补 1-2 秒尾帧或把最低阈值改成 28s。
4. 如需清理历史 SRT 缺失影响，可只对近 7 天有 MP4 的 `transcribed=2` 录音重新转录，老数据不建议全量重转。

---

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


---

## ✅ 2026-07-09 00:35 — Backfill 防重复失败 + 29.x 秒成片补尾帧

### 本次修复
1. **Director/Creative 29.x 秒边界处理**
   - 文件：`backend/transcribe.py`
   - 新增 `_pad_video_to_min_duration()`：当成片时长在 **28.0s ~ 30.0s** 时，不再直接失败，而是用 ffmpeg `tpad` 克隆尾帧并 `apad` 补音频到 **30.5s**。
   - Director 与 Creative 共用该逻辑；低于 28s 的明显异常视频仍按最低时长失败处理。

2. **无 SRT 历史组不再反复调度**
   - 文件：`backend/transcribe.py`, `backend/main.py`
   - Startup trigger / periodic director dispatch / backfill Phase 2 调度前统一检查 `_extract_srt_for_director()`。
   - 对 MP4 存在但 `.srt` 缺失的历史 Director 组，标记：
     - `director_status = -2`
     - `director_error = 'no SRT content available'`
   - 避免每次后端重启或 5 分钟周期调度都重复触发 `no SRT content available`。

3. **SQL 过滤修正**
   - 修复 `director_error IS NULL` 与 `NOT LIKE` 混用导致 NULL 待处理任务被误排除的问题。
   - 不可恢复错误（无 SRT、无录像、物理删除、时长不足、video_clips empty）统一排除。

### 验证
- `python3 -m py_compile backend/transcribe.py backend/main.py` ✅
- `git diff --check -- backend/transcribe.py backend/main.py` ✅
- 后端已重启，监听 `0.0.0.0:8899` ✅
- GPU 服务健康：`10.190.0.203:8877/health` 返回 OK，queue_depth=1 ✅
- `backend_run.log` 中 `Batches:` 计数为 0 ✅
- 重启后日志显示：
  - `Backfill: skipping 1 director groups with missing recording/SRT files`
  - 未再看到本轮启动后 `group 3703 failed: no SRT content available` 重复调度

### 当前仍未完成/阻塞
- 发布失败任务仍有约 **490** 个，核心阻塞仍是抖音 Cookie/页面超时问题，需要重新登录刷新 Cookie 后再重置可恢复发布任务。
- 历史 Director pending 仍较多（约 **1370**），其中大量是历史数据状态不一致/缺 SRT/缺素材，需要后续批量清理或按近 7 天选择性恢复。
- Creative pending 约 **528**，当前后端会继续调度 director 已完成的 Creative 组。
- GPU 侧服务仍无可用重启接口，若需 GPU 进程级修复仍需要 SSH/管理员协助。

---

## ✅ 2026-07-09 03:58 — 修复脚本 JSON 解析鲁棒性 + Tencent TTS Unicode 异常

### 当前巡检
- 后端仍在 `0.0.0.0:8899` 运行。
- GPU 服务与 watchdog 均健康：`10.190.0.203:8877/health`、`10.190.0.203:8878/health` 返回 OK。
- `backend_run.log` 中 `Batches:` 计数仍为 0，日志污染未复发。
- Publish scheduler 当前处于 00:00-07:00 低活跃时段，会跳过发布调度。

### 本次发现的新主要失败
1. `script generation: no valid JSON found in response`
   - LLM 偶发返回 markdown code fence、前后说明文本或尾随逗号，旧解析逻辑直接失败。
2. `Tencent TTS exception: 'ascii' codec can't encode character '\u2026'`
   - 文案中出现中文省略号 `…` 等 Unicode 标点时，TTS 请求/签名链路触发 ASCII 编码异常。

### 本次修复
1. **Director/Creative 脚本 JSON 提取增强**
   - 文件：`backend/director_script.py`
   - 新增 `_extract_json_object()`：
     - 支持从 markdown ```json code fence 中提取 JSON。
     - 支持从前后有说明文字的响应里按括号平衡提取首个 JSON object。
     - 自动清理对象/数组尾随逗号。
   - 目标：减少 `no valid JSON found in response` 造成的 Director/Creative 偶发失败。

2. **Tencent TTS 文本 Unicode 防护**
   - 文件：`backend/voice_director.py`
   - ASCII 编码路径改为 UTF-8；并新增 `_normalize_tts_text()` 规整高风险标点：
     - `…` → `...`
     - `—` → `-`
   - 目标：避免 TTS 遇到中文省略号/破折号时异常中断。

### 验证
- `python3 -m py_compile backend/voice_director.py backend/director_script.py backend/transcribe.py backend/main.py` ✅
- `git diff --check -- backend/voice_director.py backend/director_script.py` ✅
- 函数级自测 ✅
  - `_extract_json_object('```json\n{"a":1,}\n```')` 可解析。
  - `_extract_json_object('说明文字 {"a": [1,2,], "b": "ok",} 结束')` 可解析。
  - `_normalize_tts_text('这个颜色很好看…适合通勤—约会')` 输出 `这个颜色很好看...适合通勤-约会`。
- 后端已重启使修复生效。

### 当前仍未完成
- 发布失败任务仍约 490 个：需刷新抖音发布 Cookie 后处理。
- 低于 28s 的 Director/Creative 成片仍会失败，这是有效保护；需后续从脚本时长/TTS 时长/片段匹配侧优化。
- 少量转写 pending 与 clip failed 仍需继续观察：当前多数 clip failed 是短录像（如 10s < 30s），属于可跳过数据。

## 2026-07-09 v2.0.1 维护记录

- 直接本地修复 28~30 秒剪辑边界，不再依赖 Claude Code。
- 后端录制/剪辑硬下限从 30s 调整为 28s：`MIN_RECORDING_DURATION=28`、经典剪辑 `CLIP_MIN=28.0`、合并校验 `_MIN_DURATION_SEC=28`。
- 导演版/自编版最终视频新增统一边界：`MIN_FINAL_VIDEO_DURATION=28.0`，28s 以下直接忽略/失败，28s~30.5s 自动用 ffmpeg `tpad + apad` 补到 30.5s，避免 29.x 被 30s 最低要求卡死。
- 周期/启动调度允许旧的 28/29/30.0 秒时长失败重新入队；仍排除无录像、无 SRT、文件缺失等不可恢复错误。
- 数据库已备份后仅重置旧 28~30s 时长失败的 `clip_groups` 为待处理；未处理失败发布任务，按当前策略人工处理。
- 版本更新：README / frontend package version 升至 v2.0.1。

## 2026-07-09 16:55 — 待发布定时任务自动/批量生成标题描述

- 创建发布任务默认启用 `auto_meta=true`：用户不手填标题/描述时，后端会自动调用 AI 生成标题、描述、标签，不再产生 `(无标题)` 的定时任务。
- 批量排期弹窗默认勾选「自动 AI 生成标题和描述」，批量创建后后台逐条补齐文案。
- 发布任务列表新增「批量生成文案」按钮：仅处理 `pending/scheduled` 且标题或描述为空的任务，避免覆盖已有人工文案。
- 后端批量文案接口 `/api/publish-tasks/bulk-regen-meta` 增强：支持按状态筛选、按任务 ID 筛选、可选 `force` 重生成；默认只补齐缺失标题/描述的待发布/定时任务。
- 单条/批量文案生成统一通过 `_extract_publish_meta()` 解析 `meta_generator` 输出，兼容多方案和旧单方案结构，并用分组名兜底标题。

### 验证
- `python3 -m py_compile backend/main.py` ✅
- `npm run build`（frontend）✅
- `git diff --check` ✅

## 2026-07-11 12:26 — 下载按钮真实下载 + 抖音发布上传入口诊断/兼容

- 修复分组管理与发布页视频下载按钮：经典版 / 导演版 / 自编版下载链接补齐 `download` 属性，保留独立「▶ 预览」按钮使用原视频 URL 预览。
- 后端分组视频下载响应调整：普通点击下载时返回 `Content-Disposition: attachment`；浏览器 `<video>` 预览发起 Range 请求时仍返回 `inline`，避免破坏预览/拖动。
- 抖音发布自动化上传入口增强：不再只依赖 `input[type="file"].first`，优先匹配 video/mp4 accept 的 file input，并尝试「发布视频 / 上传视频 / 点击上传 / 选择视频」等按钮、role/text 与 upload/drag/drop 区域；点击后重新查找 input，也支持 Playwright file chooser。
- 上传入口失败时新增安全 diagnostics：记录 current URL、title、可见按钮/上传元素文本、页面关键文本片段与截图路径，保存到 `logs/publisher_diagnostics/`；不记录 cookie 内容。
- 本次未批量恢复 scheduled：外部抖音发布会打开真实创作者中心并可能真实发布，当前仅做代码级/受控验证；需先对单个任务人工确认成功后再恢复积压任务。

### 验证
- `npm run build`（frontend）✅
- `python3 -m py_compile backend/main.py backend/publisher_douyin.py backend/publish_scheduler.py` ✅
- `git diff --check` ✅
- 下载响应头验证：通过脚本对可用分组下载接口校验非 Range 为 attachment、Range 预览为 inline（若本机 DB 中存在可用样本）✅
