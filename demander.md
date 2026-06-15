# 需求清单 — douyin-recorder

> 本文件由 Claude Code 自动维护。每次对话结束前回写，新对话开始时优先读取。
> 最后更新：2026-05-08（阶段十八）

---

## 版本历史（Git Tag）

| 版本 | Tag | 日期 | 说明 |
|------|-----|------|------|
| v1.4.0 | `v1.4.0` | 2026-04-16 | 巨量千川合规改造 + 剪辑质量升级 |
| v1.5.0 | `v1.5.0` | 2026-04-21 | SQLite并发锁修复 + 自编版发布 + 批量排期重构 + 购物车筛选修复 |
| v1.6.0 | `v1.6.0` | 2026-04-21 | 发布任务过期重排期 + 文案重生成按钮 + 批量排期 meta 解析修复 |
| v1.7.0 | `v1.7.0` | 2026-04-26 | 视频时长校验 + SRT合并生成 + 无效分组合并保护 |
| v1.8.0 | `v1.8.0` | 2026-04-26 | 发布自动重试+通知+GPU告警 + 扫码验证检测 + AI文案8维度随机化 |
| v1.8.1 | `v1.8.1` | 2026-04-27 | 抖音平台建议第一批：减少套路词/多角度加权/痛点驱动/真实语气/学习系统更新 |
| v1.8.2 | `v1.8.2` | 2026-04-27 | 抖音平台建议第二批：叙事个性化/KUKU人设/信息深度/视觉质量评分/价值导向 |
| **v1.9.0** | **`v1.9.0`** | **2026-04-27** | **新潮趋势评分维度 + 「新潮种草」文案方案 + 趋势词加权30+条** |
| **v1.9.1** | `v1.9.1` | 2026-05-08 | Watchdog GPU 3D/Enc/Dec 占用率监测 |
| **v1.9.2** | `v1.9.2` | 2026-06-15 | 导演版流水线修复：LLM gzip解压错误(`Accept-Encoding: identity`) + director_video.py诊断日志增强 |

### 回退方法
```bash
# 回退到上一个稳定版本 v1.4.0
cd /Users/claw/work/douyin-recorder
git stash          # 保存当前未提交改动（如有）
git checkout v1.4.0

# 重启后端
kill $(lsof -ti:8899)
cd backend && nohup uvicorn main:app --host 0.0.0.0 --port 8899 >> /private/tmp/douyin_backend.log 2>&1 &

# 恢复到最新版本
git checkout main
```

---

## 规则约定

- **Claude Code 发起剪辑作业时，每次至多调入 2 个任务**，避免占用过多资源。

---

## 硬件环境

| 节点 | 硬件 | 职责 |
|------|------|------|
| 本机 | M2 8GB 统一内存 | 编排/ffmpeg编辑/FastAPI后端/前端 |
| GPU 服务器 | RTX 4080 SUPER 16GB，IP: 10.190.0.203 | Whisper 转录(:8877) + ComfyUI(:8188) + Watchdog(:8878) |

**关键约束：本机仅 8GB 统一内存，macOS 基础占用 ~3.5GB，可用于视频处理上限约 4GB。**

---

## 内存爆炸根因分析（已解决）

### 原始问题
上一次运行内存达 45GB 等效（macOS 大量 Swap），系统弹出"应用内存不足"强制终止。

### 根因链
1. `MAX_CONCURRENT_CLIPS` 默认值为 2，启动 2 个并发剪辑任务
2. 每个任务内 `_gen_transition_anime_frames` Semaphore=3、`_gen_zoom_punch_clips` Semaphore=3
3. 2 任务 × Semaphore(3) = 最多 6 路并发 4K ffmpeg VideoToolbox 进程
4. VideoToolbox 在 Apple Silicon 上分配 Metal buffer，无法 Swap，直接吃统一内存
5. 输出分辨率 4K(2160×3840)，每路 VideoToolbox 需 1~2GB → 6 路 = 6~12GB，严重超出 8GB
6. 内存监控阈值 `MEM_WARN_GB=20` 在 8GB 机器上永远触发不了（形同虚设）

---

## 阶段十八：Watchdog GPU 占用率监测（已完成 2026-05-08）

### 背景
健康化烡检脏查中只能看到 GPU 服务是否在线，无法知道 GPU 当前负载。

### 改动清单

| 文件 | 改动 |
|------|------|
| `gpu_service.py`（GPU服务器） | `/health` 端点新增 `gpu_3d_pct`、`gpu_mem_pct`、`gpu_enc_pct`、`gpu_dec_pct` 四个字段（`nvidia-smi dmon -s u -c 1`，timeout=5s，失败静默） |
| `watchdog_agent.py`（GPU服务器） | `_probe_health` 拆分为 `_probe_health_with_data`；`/status` 端点在 gpu 服务 healthy 时透传四个占用率字段 |
| `frontend/src/components/GpuBanner.vue` | ComfyUI 在线时展示 `3D%` 和 `Enc%` 进度条 |
| `scripts/fix_stuck_jobs.py` | 已巡棄日志同步显示 GPU 占用率 |

### GPU 占用率字段说明（nvidia-smi dmon sm/mem/enc/dec）

| 字段 | 含义 |
|------|------|
| `gpu_3d_pct` | SM/3D 平均占用率（Whisper 推理时高） |
| `gpu_mem_pct` | 显存控制器占用率 |
| `gpu_enc_pct` | NVENC（Video Encode）占用率（ffmpeg 编码时高） |
| `gpu_dec_pct` | NVDEC（Video Decode）占用率 |

---

## 阶段十七：新潮趋势评分维度（已完成 2026-04-27）

### 背景
抖音平台「商品新潮有趣」评分维度：品牌新品/联名限定/趋势色/时令款 是推流加分项。

### 改动清单

| 文件 | 改动 |
|------|------|
| `backend/editor.py` | `_SCORES` 新增「新潮/趋势/限定」词组 30+ 条，权重 8-12；联名款/限量款 12，趋势色/今年流行色 11，新品/上新/最新款 10-11 |
| `backend/editor.py` | `_HIGHLIGHT_PRODUCT` 加入联名/限量/新款/Y2K/法式/日系/韩系/复古等风格词 |
| `backend/editor.py` | `_SCENE_KW` 加入街拍/穿搭/出片/上镜/ins/小红书（新潮调性场景词）|
| `backend/segment_scorer.py` | `_LLM_TEXT_PROMPT` 新增「新潮趋势性」加分维度 |
| `backend/meta_generator.py` | `_SCHEME_POOL` 新增「新潮种草」方案（方案池扩至10个，随机取4）；通用规则补充限量/联名使用规范（禁止无依据声称）|
| `backend/director_script.py` | 新增规则15：SRT 出现趋势词时必须提炼为 key_messages |

---

## 阶段十六：抖音评分第二批 — 叙事个性化 + 视觉质量（已完成 2026-04-27）

### 背景
抖音「创作风格独特」「人设清晰鲜活」「价值导向正向」「视听氛围良好」四维度。

### 改动清单

| 文件 | 改动 |
|------|------|
| `backend/director_script.py` | 叙事结构从固定模板改为 A/B/C 三选一（痛点驱动/细节发现/社交验证）；新增规则 11-17（独特视角、细节代替形容词、场景具体化、情感弧线、信息三维覆盖、增值内容优先、趋势词识别）|
| `backend/director_script.py` | 新增 `kuku` vibe 配置（专业假发博主视角，medium节奏，有个人观点，轻催单）+ `_build_kuku_prompt` 方法 |
| `backend/meta_generator.py` | 新增【信息深度要求】（外观/功能/体验三维覆盖，增值信息提炼）；新增【价值观导向】（禁焦虑营销，强调自我愉悦，平等视角）|
| `backend/segment_scorer.py` | `_VISION_PROMPT` 新增 `lighting_quality`（光线质量）和 `motion_stability`（运动稳定性）两个评估维度；`_semantic_bonus` 新增对应加减分（抖动严重最高 -7.5）；`maxTokens` 200→250 |
| `backend/editor.py` | `_SCORES` 新增画面构图词（特写镜头/近距离/放大看/镜头拉近推进）和视觉质感词（光泽/质感/质地/摸起来/手感）|

---

## 阶段十五：抖音评分第一批 — 文案质量 + 多角度评分（已完成 2026-04-27）

### 背景
抖音「信息真实有用」维度5条建议：减少套路词/多角度展示/解决痛点/真诚语气/学习系统更新。

### 改动清单

| 文件 | 改动 |
|------|------|
| `backend/meta_generator.py` | 禁止空洞形容词（氛围感/仙气/高级感）；要求每条文案含1个具体参数；新增「痛点解决」方案维度；强制第一人称叙事，禁止连续感叹号；文案允许1个真实局限 |
| `backend/segment_scorer.py` | `_SCORES` 提升多角度词权重（侧面7→10，背面6→10，360 9→12）；新增 `angle_variety`(+3.0) 和 `has_scene_context`(+2.0) 两个 vision 评分维度 |
| `backend/editor.py` | 新增室内/户外/自然光/各个角度等场景对比词；`_SCENE_KW` 补充多场景词 |
| `backend/segment_scorer.py` | `_LLM_TEXT_PROMPT` 新增多角度/具体参数/痛点解决/真实口语四个评分维度 |

---

## 阶段十四：发布自动重试 + 杂详修复 + AI文案随机化（已完成 2026-04-26）

### 问题
1. **发布失败无重试**：发布失败后直接标记失败，无通知运维人员
2. **GPU 离线无预警**：GPU 连接断开后应用静默失败，没有任何告警
3. **发布后扫码验证弹窗无法处理**：押下发布后平台偶尔弹出扫码安全验证，代码未处理
4. **AI文案同质化**：固定 4 种方案（种草/催单/产品介绍/教学），每次文案风格局限，标题开头套话重复
5. **登录失效重试浪费**：登录失效错误列为可重试，白白重试 2 次
6. **`input[type="file"]` 超时**：抖音上传页为 React SPA，`domcontentloaded` 后元素未渲染，文件选择器找不到
7. **quick-check indeterminate 卡死**：快速检查状态不确定时进入手动流程，实际应自动发布

### 改动清单

| 文件 | 改动 |
|------|------|
| `backend/notifier.py` | 新增：封装 `openclaw system event --text "..." --mode now` 推送 OpenClaw 通知 |
| `backend/publish_scheduler.py` | 发布自动重试最多 2 次（间隔 30s）；成功/失败均通知；新增 `retry_count` 字段 |
| `backend/gpu_state.py` | GPU 离线 ≥ 5min 自动推送告警通知；恢复时推送恢复通知 |
| `backend/db.py` | `publish_tasks` 表迪移 `retry_count INTEGER DEFAULT 0` |
| `backend/publisher_douyin.py` | `domcontentloaded` 后追加 `networkidle` 等待 SPA hydration；`input[type="file"]` 先直接等 30s，失败则点击上传区域触发动态生成，再等 60s |
| `backend/publisher_douyin.py` | `_wait_for_quick_check` indeterminate 时，发布按鈕可见则自动点击，不进手动流程 |
| `backend/publisher_douyin.py` | `non_retryable` 增加 `"Not logged in"`/`"login QR code"`/`"Cookie may have expired"` |
| `backend/publisher_douyin.py` | 新增 `_handle_scan_verify()`：点击发布后 1.5s 内检测扫码验证弹窗，出现则 banner 提示用户扫码，最多等待 5 分钟 |
| `backend/publisher_douyin.py` | 移除 `page.wait_for_event("close")` race；改为 `wait_for_url` + URL 检查 |
| `backend/meta_generator.py` | `_SCHEME_POOL` 8 个方案维度（社交认可/自我改变/场合穿搭/细节种草/产品介绍/使用教学/价值催单/疑问引发） |
| `backend/meta_generator.py` | `_build_meta_prompt()`：每次用 `random.sample` 随机抖 4 个组合，动态填充 prompt；`generate_meta` 改用新函数并记录 log |

### git commits
- `da13871` feat: 发布自动重试(2次) + OpenClaw失败/成功/GPU离线通知
- `0ab1532` fix: 抖音上传页networkidle等待 + input[type=file]点击触发fallback + quick-check indeterminate时自动发布
- `66055fd` fix: 登录失效错误列为不可重试，避免无意义重试两次
- `5ed4943` fix: 点击发布后等待扫码验证弹窗 + 移除误触发的page close race
- `38687eb` feat: AI文案方案池扩展到8维度，每次随机扠4个，消除同质化

---

## 阶段十三：视频质量保障 + AI文案优化（已完成 2026-04-26）

### 问题
1. 分组合并视频时长 < 30s：`merge_group` 三条合并路径合并后未校验总时长，短视频照样写入 DB 并流入发布队列
2. AI 生成标题/描述质量差：`meta_generator` 期望读取 `merged_XXX.srt` 但从未生成该文件，Bedrock 收到「无字幕」，生成通用模板文案，款式/颜色张冠李戴
3. `clipped=-1` 时 `merge_group` 仍被调用：手动触发合并（`trigger_merge`）缺少前置检查，产生无意义的空分组
4. 导演版/自编版缺少时长校验：经典版已有校验，但 `_run_director_pipeline` 和 `_run_creative_pipeline` 写 status=2 前没有 ffprobe 验证

### 改动清单

| 文件 | 改动 |
|------|------|
| `backend/analyzer.py` | 新增 `_probe_duration()`（async ffprobe）+ `_ShortDurationError`；三条合并路径（GPU concat/classic-concat/本地ffmpeg）下载完成后校验时长，< 30s → 删文件 + `classic_status=-2` + `merge_error` |
| `backend/analyzer.py` | 新增 `_build_merged_srt(group_id, merged_filename)`：合并成功后拼接各录像 SRT（去序号/时间戳），写 `recordings/<merged_name>.srt`；三条路径均调用 |
| `backend/meta_generator.py` | 提取 `_read_srt_text()` 辅助；新增 `_get_srt_excerpt_with_fallback()`：先读 merged SRT，再逐条录像 SRT 回退；`generate_meta()` 改用新函数 |
| `backend/main.py` | `trigger_merge` 手动触发前查 `clipped=2` 录像数，为 0 则跳过经典版合并，写 `classic_status=-1` + `merge_error='无有效剪辑片段，无法合并'` |
| `backend/transcribe.py` | `_run_director_pipeline_inner`：`compose_final_video` 返回后加 ffprobe 时长校验，< 30s → 删文件 + `director_status=-1` |
| `backend/transcribe.py` | `_run_creative_pipeline_inner`：同上，< 30s → 删文件 + `creative_status=-1` |

### 历史数据清理
- 批量为 1095 个已有分组生成了 merged SRT（Python 脚本直接拼接）
- 26 个历史短视频（经典版 < 30s）标记为 `classic_status=-2`
- 发现历史导演版也有 < 30s 的（如 group 2517：11.7s），已通过 Claude Code 清理

---

## 阶段十二：发布任务 UX 修复（已完成 2026-04-21）

### 问题
1. 批量排期创建的所有任务无标题（meta schemes 格式解析错误，`meta["title"]` 为 None）
2. 过期的定时任务没有重新排期入口
3. 无法手动重生成单条任务的文案

### 改动清单

| 文件 | 改动 |
|------|------|
| `backend/main.py` | 新增 `PATCH /api/publish-tasks/{id}`（修改 scheduled_at，自动重置 status=scheduled）；修复 `_fill_meta_background` 和 `regen_publish_task_meta` 的 schemes 格式解析（取 `schemes[0]["title"]` 而非 `meta["title"]`）；新增 `POST /api/publish-tasks/{id}/regen-meta` |
| `frontend/src/api.js` | 新增 `regenPublishTaskMeta()`、`reschedulePublishTask()` |
| `frontend/src/views/Publish.vue` | 任务列表行：过期 scheduled 任务加「↻」重新排期按钮；详情面板：加「重新排期」（黄色）+ 「重生成文案」按钮；新增重新排期弹窗；新增 `isExpired()`、`openReschedule()`、`submitReschedule()`、`regenMeta()` 函数 |

---

## 阶段十一：SQLite并发修复 + 发布系统增强（已完成 2026-04-21）

### 问题根因
多个 aiosqlite 连接并发写 SQLite，默认 timeout=5s 导致 `database is locked`，所有写操作（创建发布任务、触发合并）持续 500 错误。

### 改动清单

| 文件 | 改动 |
|------|------|
| `backend/db.py` | 新增 `aio_connect(timeout=30)` 辅助函数；`init_db` 启动时开启 WAL 模式 + `busy_timeout=30000` |
| `backend/main.py` + 7个后端文件 | 全部 172 处 `aiosqlite.connect(DB_PATH)` 替换为 `aio_connect()`（timeout=30s） |
| `backend/main.py` | `create_publish_task` 重复检测查询补 `db.row_factory = aiosqlite.Row`（修复 TypeError: tuple indices must be integers） |
| `backend/main.py` | `batch_schedule_tasks` 两阶段重构：Phase 1 立即插入所有任务返回，Phase 2 `asyncio.create_task` 后台补充 meta——消除批量排期卡死 |
| `backend/main.py` | `_fill_meta_background` + `regen_publish_task_meta` 修复 schemes 格式解析（`meta["schemes"][0]` 取 title，而非 `meta["title"]`） |
| `backend/main.py` | 新增 `POST /api/publish-tasks/{task_id}/regen-meta` 端点（手动重生成单条任务文案） |
| `backend/main.py` | `unscheduled-groups` + `batch-schedule` SQL 加入 `creative_status=2` 和 `creative_final_video`，自编版分组现可进入发布待选 |
| `backend/main.py` | `create_publish_task` + `batch-schedule` 视频选择逻辑加入 `creative` 分支（both 模式：导演版 > 自编版 > 经典版） |
| `frontend/src/views/Publish.vue` | 直播间 chip 切换时清空已选分组和商品，修复购物车商品不跟直播间变化的 bug |

### v1.5.0 功能摘要
- **批量排期**：秒级返回，meta 在后台异步生成，不再卡死
- **自编版**：进入「批量排期」和「单个发布」的分组候选列表
- **购物车**：切换直播间 chip 时商品列表同步刷新
- **文案重生成**：发布任务可单独触发重新生成 title/description

---

## 阶段一：OOM 修复（已完成 2026-03-25）

### 改动文件清单

| 文件 | 改动 | 原因 |
|------|------|------|
| `backend/transcribe.py:56` | `MAX_CONCURRENT_CLIPS` 默认 `"2"` → `"1"` | 8GB 不允许双任务并发 |
| `backend/editor.py:281-282` | `OUT_W/OUT_H` 4K(2160×3840) → 2K(1080×1920) | ÷4 内存，VideoToolbox buffer 大幅减少 |
| `backend/editor.py:866` | `sem_frames` Semaphore(3) → Semaphore(1) | 消除最大内存峰值来源 |
| `backend/editor.py:925` | `sem_zoom` Semaphore(3) → Semaphore(1) | 同上 |
| `backend/editor.py` 多处 | 预编码码率 20M→10M，xfade 15M→8M，final 20M→10M | 2K 下 10Mbps 已足够清晰 |
| `backend/main.py:78-80` | `MEM_WARN_GB` 20→5，`MEM_RECOVER_GB` 17→4，`INTERVAL` 30→10 | 修复 8GB 机器上内存监控失效 |
| `backend/thumbnail.py:189` | 帧提取 4K→2K | 消除隐藏的 4K ffmpeg 内存开销 |
| `backend/thumbnail.py:225` | PIL 合成尺寸 4K→2K | 减少 PIL 内存占用（32MB→8MB per frame） |

### 预期效果
- 内存峰值：~30~45GB → **~4~5GB** ✅
- 单任务串行，ffmpeg 最多 1 路重载进程 + 1 路轻量帧提取
- 内存监控有效，超过 5GB 立即触发 gc + 暂停派发

---

## 阶段十：商品库增强 + 发布任务批量取消（已完成 2026-04-19）

### 改动清单

| 文件 | 改动 |
|------|------|
| `backend/db.py` | `products` 表新增 `product_thumb TEXT` 字段迁移（商品缩略图URL） |
| `backend/models.py` | `ProductCreate`/`ProductUpdate` 加 `product_thumb` 字段 |
| `backend/main.py` | 新增5个商品端点：`GET /check-url`（链接去重检测）、`GET /duplicate-urls`（现有重复列表）、`POST /import-excel`（Excel导入）、`GET /template.xlsx`（模板下载）；INSERT语句加 `product_thumb`；Excel模板加 `product_thumb` 列；`DELETE /publish-tasks/bulk-cancel`（批量取消定时任务，路由在 `/{task_id}` 前）；路由顺序修正 |
| `frontend/src/api.js` | 新增 `bulkCancelPublishTasks()` |
| `frontend/src/views/Products.vue` | 全面重写：直播间筛选下拉、关键词搜索、链接重复检测（现有重复展开面板+行标红）、新增时实时链接去重、Excel/JSON双模式批量导入+拖拽+模板下载、商品名悬停缩略图预览（用 `product_thumb` 字段）、新增弹窗加缩略图URL输入 |
| `frontend/src/views/Publish.vue` | 小黄车商品列表加关键词搜索框（`cartSearch`+`cartFilteredProducts` computed）；发布任务面板顶部加「批量取消」按钮（黄色警示样式） |

### 商品库功能说明（当前生效）
- **直播间筛选**：顶部下拉，选某直播间后只显示该直播间商品（含无关联商品）
- **链接重复检测**：`🔍 重复检测` → 展开重复面板，行标红+重复徽章；新增弹窗链接输入失焦自动检测
- **Excel批量导入**：支持拖拽上传 `.xlsx`，列名 `product_name/product_id/product_url/product_thumb/keywords/platform/room_id`；`⬇ 下载导入模板` 提供标准模板
- **商品缩略图**：`product_thumb` 字段存图片URL（抖音商品图需手动填写或通过采集工具写入）；有缩略图的商品名下方有虚线，鼠标悬停300ms后弹出160×160预览
- **批量取消定时任务**：发布页顶部「批量取消」，取消所有 `pending/scheduled/failed` 状态任务

---

## 阶段九：三模式并行全面打通（已完成 2026-04-18）

### 问题
自编模式（creative）流水线代码在 `transcribe.py` 中已存在，但 DB 字段未迁移、`trigger_merge` 未触发、前端无展示，导致三模式并行实际上只有双模式。

### 改动清单

| 文件 | 改动 |
|------|------|
| `backend/db.py` | 补充5个 creative 字段迁移：`creative_status`、`creative_error`、`creative_script`、`creative_audio_path`、`creative_final_video` |
| `backend/main.py` | `trigger_merge` 同时触发三条流水线（classic + director + creative）；409判断改为三条全在运行才拦截；reset 语句加 `creative_error`/`creative_status`；`publish_versions` 合法值加 `creative` |
| `backend/main.py` | 新增 `GET /api/groups/{id}/creative-download` 端点（带 Range 支持） |
| `frontend/src/views/Groups.vue` | 发布版本选择器加 `✍️ 自编版` 选项；group-actions 加自编版状态徽章 + `▶ 自编版` 预览按钮 + `↓` 下载按钮；新增自编版 preview modal；JS 加 `creativePreviewGroup/Error` ref 和 open/close 函数；CSS 加 `.btn-action.green` |

### 三模式并行架构（当前生效）

每次"剪辑并合并"或 `_auto_merge_group` 自动触发时，同时启动三条独立流水线：

| 模式 | 流水线函数 | DB 状态字段 | 视频字段 | 特点 |
|------|-----------|------------|---------|------|
| 经典版 | `merge_group()` | `classic_status` | `merged_filename` | 关键词评分+叙事结构，纯本地 |
| 导演版 | `_run_director_pipeline()` | `director_status` | `director_final_video` | SRT→脚本→TTS→GPU合成 |
| 自编版 | `_run_creative_pipeline()` | `creative_status` | `creative_final_video` | 空SRT→自由创作脚本→TTS→GPU合成 |

- 三条流水线各自独立，互不影响，任意一条失败不影响其他两条
- `publish_versions` 支持：`both`（全部）/ `classic` / `director` / `creative`
- 崩溃恢复：`backfill_auto_merge` 启动时自动重启三条流水线中卡在 status=1 的那条

---

## 阶段八：导演模式优化 + 队列稳定性修复（已完成 2026-04-18）

### 改动清单

| 文件 | 改动 |
|------|------|
| `backend/main.py` | `/api/gpu/status` 端点改用 aiohttp 探测 ComfyUI（8188）和 GPU；消除该端点挂死导致仪表盘 GPU 状态永远显示离线的 bug |
| `backend/segment_scorer.py` | `_call_bedrock_vision` timeout 30s → 8s；防止大批量段落 semantic scoring 因反复 30s 超时卡死整个剪辑队列 |
| `backend/director_video.py` | 删除蓝色（`_B_BLUE`）和紫色（`_B_PURPLE`）描边层，只保留 `_B_TEXT`；字幕改为整句显示（覆盖完整 TTS 时长），不再按 12 字切块分时；`MAX_CHARS` 12→14 |
| `backend/voice_director.py` | KUKU公主（room_id=2）TTS speed 1.1 → 1.21（+10%） |
| `backend/director_script.py` | 重写文案生成 prompt：从"爆款营销套路"改为"忠实于直播内容的产品介绍"；明确禁止"等等等等""你看你看""注意注意"等填充词；禁止编造催单内容；叙事结构改为产品介绍顺序；新增铁律6（文案连贯性） |
| `frontend/src/views/Groups.vue` | 经典版合并完成后新增 `▶ 经典版` 预览按钮（弹出视频 modal）+ `↓` 下载按钮；新增经典版预览 modal |

### 字幕规范（当前生效）
- **导演模式**：只保留单层 `_B_TEXT`（半透明深色描边白字），无蓝色/紫色描边
- 每句话整段显示，时长与 TTS 语音对齐，最多显示 2 行 × 14 字

### 导演脚本文案规范（当前生效）
- 100% 来源于直播转录内容，不编造、不夸大
- 叙事结构：开场介绍 → 外观/颜色/款式 → 演示效果 → 适合人群 → 引导关注
- 禁止填充词：等等等等、你看你看、注意注意、哇哦、OMG、绝绝子等
- 除非直播里明确提到，否则不写库存/断货/紧迫感内容
- KUKU公主 TTS 语速 1.21x，其他直播间 1.1x

---

## 阶段七：httpx→aiohttp 全面修复 + GPU 探测修复（已完成 2026-04-17）

### 根本 Bug 修复

GPU 服务器（10.190.0.203:8877）与 `httpx` 库存在兼容性问题：TCP 连接可以建立，但 HTTP 读取会一直挂起直到超时（ReadTimeout），而 `curl` 和 `aiohttp` 完全正常。

**影响范围**：所有直接与 GPU 服务通信的模块，导致：
1. `gpu_state.py`：探测始终失败 → 后端认为 GPU 离线 → 编辑任务全部走本地降级
2. `segment_scorer.py`：99个段落各等 20s 超时 = 每个录像 **33分钟** 才能进入队列
3. `editor.py`：clip-job 提交/轮询/下载全部失败 → 回退本地编辑
4. `director_video.py`：导演模式 GPU 合成失败
5. `voice_director.py`：TTS 任务提交/轮询/下载全部失败

### 改动清单

| 文件 | 改动 |
|------|------|
| `backend/gpu_state.py` | `_probe_gpu` 改用 aiohttp（read timeout 30s） |
| `backend/editor.py` | `_edit_via_gpu`（clip-jobs POST/轮询/下载）+ rembg GPU 调用 httpx → aiohttp |
| `backend/segment_scorer.py` | `_extract_frame_gpu`（/jobs/{id}/extract-frames）httpx → aiohttp |
| `backend/director_video.py` | director-jobs POST/轮询/下载 + `_ensure_clips_on_gpu` httpx → aiohttp |
| `backend/voice_director.py` | voice-refs 验证/提交/轮询 + tts-jobs POST/轮询/下载 httpx → aiohttp |
| `backend/transcribe.py` | `_check_job`（/jobs/{id} 轮询）+ `_fetch_srt`（/jobs/{id}/srt 下载）httpx → aiohttp |
| `backend/analyzer.py` | `_gpu_concat`（concat-jobs POST/轮询/下载）httpx → aiohttp |
| `backend/sync.py` | `sync_file`（/jobs 文件上传）httpx → aiohttp |
| `backend/capcut_editor.py` | capcut/drafts POST + compare POST httpx → aiohttp |

**注意**：Bedrock（AWS）、MiniMax、腾讯云等外部 HTTPS API 仍使用 httpx，不受影响。

### SEG_PAD 修复（同期）

| 文件 | 改动 |
|------|------|
| `backend/editor.py` | `SEG_PAD = 0.5 → 0.0`（消除片段间音频重复） |
| `gpu_service/main.py` | `SEG_PAD = 0.5 → 0.0`（同步修复，已部署到 GPU 服务器） |

---

## 阶段六：字幕优化 + 发布质量门槛（已完成 2026-04-16）

### 改动清单

| 文件 | 改动 | 原因 |
|------|------|------|
| `backend/editor.py` | 字幕字体 80pt→**104pt**，KWPOP 130pt→**169pt**（+30%） | 字幕在移动端更易阅读 |
| `backend/editor.py` | 描边层加 `\3a&H80&`（50% alpha），`OutlineColour` 改 `&H80141414` | 半透明描边不遮挡画面 |
| `backend/director_video.py` | 同步字体和描边修改（XQN/KWPOP style + `_B_BLUE/_B_PURPLE/_B_TEXT`） | 经典/导演模式一致 |
| `backend/publish_scheduler.py` | 最短发布时长 **42s → 30s** | 与剪辑规范对齐 |
| `backend/publish_scheduler.py` | 发布调度轮询：`pending` 任务等待由 **90s → 5s** | 提交任务后秒级弹出浏览器 |
| `backend/main.py` | 新增5个端点：review-candidates / review / rule-suggestions / accept / reject | 人工审核片段 + 规则建议系统 |
| `frontend/Groups.vue` | 每个剪辑新增「审核」按钮；片段勾选弹窗；规则建议面板 | 人工审核入口 |

### 字幕规范（当前生效）
- 字体：新青年体 104pt（底部字幕），169pt（右上角KWPOP弹跳大字）
- 描边：3层渐变（蓝→紫→深色），全部 50% 半透明
- 背景色：`&H80000000`（半透明黑底），保持可读性

### 发布质量门槛（当前生效）
- 分辨率 ≥ 1080×1920（2K竖屏）
- 帧率 ≥ 25fps
- 时长 ≥ **30秒**

### 人工审核系统（已部署）
- 「审核」按钮：每个完成剪辑旁新增，打开片段勾选弹窗
- 勾选保留/取消 = 告知系统关键词是否有效
- 提交后自动触发 `run_training_cycle()` → 生成 `rule_suggestions`
- 工具栏「规则建议 (N)」面板：接受→写 `rule_overrides`+热更新 `_SCORES_EFFECTIVE`；忽略→标记 rejected

---

## 阶段五：剪辑质量全面升级（已完成 2026-04-16）

### 需求背景
用户反馈：剪出来的视频太短（10-20s）、叙事不完整、转场单一、细节不放大、缺少关键词艺术字弹出。

### 改动清单

| 文件 | 改动 | 原因 |
|------|------|------|
| `backend/editor.py` | `CLIP_MIN=30s`, `CLIP_MAX=90s`（legacy）；`CLIP_MIN_V2=46s`（v2）| 保证输出视频达到平台优质时长 |
| `backend/editor.py` | product/wearing narrative budget `10s/3段` → `20s/6段` | 一款假发完整介绍不被截断 |
| `backend/editor.py` | 段落最大时长 `max_dur`: 产品类 `12s→18s`，普通 `8s→10s` | 完整保留一句话不截断 |
| `backend/editor.py` | `_HAIR_DETAIL_KW` 扩展至所有 detail 类词；detail 类段落一律强制 `push_in_strong` | 细节讲解时镜头放大发丝区域 |
| `backend/editor.py` | `_edit_via_gpu` payload 增加 per-segment `transition`/`transition_duration` | 经典模式转场多样化（slideleft/smoothleft等） |
| `backend/editor.py` | `build_ass` 新增 Layer 3 `KWPOP` style（104pt→169pt金色，右上角Alignment=9）；含关键词句子触发弹跳动画 | 高光关键词右上角大艺术字弹出 |
| `backend/director_video.py` | `_DIR_ASS_HEADER` 新增 `KWPOP` style；`_build_director_ass` 新增 Layer 3 弹跳动画 | 导演模式与经典模式保持一致 |
| `backend/main.py` | `/api/reclip` 批量接口传 `feedback=rec["reclip_feedback"]` | 批量重剪时反馈参与 LLM hint 生成 |
| `gpu_service/main.py` | `_nvenc_xfade_merge` 支持 4-tuple `(path, dur, transition, tr_dur)`；新增 `_VALID_XFADE_CLASSIC` 白名单 | GPU端按段落使用不同转场 |

### 剪辑规范（当前生效）
- **时长**：30s–90s（经典/v2 均适用）
- **叙事结构**：完整介绍一款产品，不截断句子，product+wearing合计最多40s预算
- **运镜**：detail 类/细节关键词 → `push_in_strong`（1.0x→1.20x 推进放大）
  - 触发词（部分）：发丝、发根、发缝、头皮、分缝、特写、细节、**耳后、耳边、后脑勺、鬓角、两鬓、发际线、颈后、放大、拉近**
- **转场**：经典模式按 narrative position 从池中随机选（slideleft/smoothleft/phone_zoom等），不再全部 dissolve
- **字幕**：底部3层渐变描边白字 + 关键词金色；右上角 KWPOP 层弹跳大字（每句含高亮词时触发）

### 自学习系统（已部署）
- 重剪时输入的反馈 → `reclip_feedback` 存 DB → `_feedback_to_hints`（Bedrock Claude）→ 当次剪辑 preferred_ranges / boost_keywords
- LLM 发现关键词分数异常 → 写 `rule_suggestions` 表 → 人工在前端"规则建议面板"审核 → 接受后写 `rule_overrides` → 下次重启生效
- **不自动写 rule_overrides**，需人工审核

---

## 阶段四：CosyVoice2 TTS 声音克隆（已完成 2026-04-14）

### 根本 Bug 修复

`Qwen2Encoder.forward_one_step` 在 KV cache 步骤中传 `attention_mask=(1,1)`，与 transformers 5.3.0 DynamicCache+SDPA 不兼容，导致每步 hidden state 偏差≈19，EOS 概率始终 logp≈-5~-15，从不被采样，每次生成满 max_len 的乱码"gu lulu"音频。

**修复文件**：`C:\Users\neo\CosyVoice\cosyvoice\llm\llm.py` → `forward_one_step` 拼接 full mask `(1, past_len+1)`。

### 声音克隆架构

| 接口 | 功能 |
|------|------|
| `POST /voice-refs/upload` | 上传 WAV/MP3，绑定 room_id+label，自动转录 |
| `POST /voice-refs` | 从已有 MP4 录像截取片段 |
| `GET /voice-refs?room_id=1` | 列出某直播间所有声音版本 |
| `POST /tts-jobs` with `room_id` | 自动用该直播间最新声音生成 TTS |

TTS 模式选择：有 ref → `inference_zero_shot`（LLM+flow 双重克隆）；无 ref → `inference_instruct2` 降级。

### 小圆圆不圆（room_id=1）声音版本

| 版本 | ref_id | 来源 | 状态 |
|------|--------|------|------|
| v1 | `f44a4657b8d24086` | `.aac` 5kbps 直播流 | 保留备份 |
| v2 | `eed04d90f4f345f2` | MP4 98kbps + 降噪 | 保留备份 |
| v3 | `989822da2e854ee9` | 无损 WAV 1536kbps + SRT 精准 transcript | 保留备份 |
| **v4（当前默认）** | `1ee58eb99c61474a` | 4月15日直播片段，节奏自然，speed=1.21x | ✅ 用户确认 |

**源文件**：`/Users/claw/Documents/4月13日(2).wav`，截取 00:09:00.8~00:09:15.6（14.8s）。

---

## 阶段三：导演模式 GPU 迁移（已完成 2026-04-11）

### 改动文件清单

| 文件 | 改动 |
|------|------|
| `gpu_service/main.py` | 新增 `/director-jobs` 端点（POST/GET/GET-mp4）；`_do_director_job` 处理多源 NVENC 合成；`_nvenc_director_merge` 可配置转场类型；`_director_sem=Semaphore(1)` |
| `backend/director_video.py` | `compose_final_video` 改走 GPU；新增 `_build_director_ass`（本地 ASS 含关键词高亮）；`_ensure_clips_on_gpu` 自动同步源文件；`_find_recording_file` 返回 `{path, room_id, filename}` |
| `backend/main.py` | `trigger_merge` 按 `editing_mode` 分发：`director`→`_run_director_pipeline`，其他→`merge_group` |
| `backend/editor.py` | 新增 `_HIGHLIGHT_ACTION` 关键词集（佩戴/造型动作词：分两份/往里塞/皮扣一勾/防风扣/固定/戴上/梳开等），合并进 `_HIGHLIGHT_KW` |
| `backend/director_video.py` | `_DIR_HIGHLIGHT_ACTION/PRODUCT/SCENE` + `_split_by_keywords`；`_make_subtitle_png` 新增关键词金色叠加层（Pillow alpha_composite） |

### 架构说明（导演模式）

```
本机（编排层）
  脚本生成（Bedrock）→ 片段匹配 → ASS 字幕构建（含关键词高亮）→ TTS base64 编码
  → POST /director-jobs → 轮询 GET /director-jobs/{id} → 下载 MP4

GPU 服务器（处理层）
  Phase 1: 各 clip 独立 NVENC 预处理（trim + scale + pad + unsharp）
  Phase 2: xfade 树状合并（可配置转场类型，NVENC 重编）
  Phase 3: ASS 字幕烧录（FONTS_DIR 字体）+ TTS 音频替换（h264_nvenc + aac）
  Phase 4: 封面帧提取
```

---

## 阶段二：GPU 卸载（待开发）

### 核心发现
**源 MP4 文件在转录时已上传到 GPU 服务器并永久保存于 `/data/douyin-recordings/`，无需重复上传。**

### 卸载方案

#### ① ffmpeg 编辑流水线迁移至 GPU（价值最高）

在 `gpu_service/main.py` 新增 clip job API：

```
POST /clip-jobs
  body: {
    mp4_filename,        # 已在 GPU 服务器上（转录时上传）
    room_id,
    segments: [{start, end}, ...],
    srt_content,         # Mac 本地生成 ASS 字幕后传入
    output_resolution: "1080x1920"
  }
GET /clip-jobs/{job_id}          # 进度查询
GET /clip-jobs/{job_id}/mp4      # 下载最终 clip（2K ~50-100MB）
GET /clip-jobs/{job_id}/thumb    # 下载缩略图
```

Mac 端 `editor.py` 改为：片段评分选择 → 生成 ASS 字幕 → 发 clip job → 下载结果。

**优势：**
- NVENC（独立硬件单元）不竞争 VRAM，与 Whisper/ComfyUI 可同时运行
- NVENC 编码速度比 VideoToolbox 快 3~5×
- Mac 完全释放 VideoToolbox 内存压力
- 网络开销：仅下载结果 clip（50-100MB，1Gbps ~0.8s，100Mbps ~8s）

#### ② rembg 迁移至 GPU CUDA（次高价值）

在 GPU 服务新增：
```
POST /rembg     # 传入 JPEG → 返回 PNG（U2Net 背景去除）
```

- 当前 Mac CPU 推理：5~30 秒/帧 + 1.5~2GB 内存
- GPU CUDA 推理：< 0.5 秒/帧 + 0 Mac 内存

#### ③ 保留在本机的任务

- 片段评分/选择（纯 Python，无算力）
- ASS 字幕文本生成（纯文本）
- noisereduce（6s 音频，< 1s CPU）
- Bedrock API（已是远程调用）
- Publisher Playwright（必须本机）
- DB 管理、目录监控

### GPU 服务器资源评估

```
同时运行时 VRAM 使用：
  Whisper large-v3：   ~3 GB VRAM（转录时）
  ComfyUI AnythingV5：  ~6~8 GB VRAM（动漫帧时）
  NVENC ffmpeg：         0 GB VRAM（独立硬件单元）
  rembg CUDA：         ~0.5 GB VRAM
  ─────────────────────────────────────
  最坏并发：            ~11 GB < 16 GB ✅
```

### GPU 离线降级策略
- GPU 服务离线时，Mac 本地以 `MAX_CONCURRENT_CLIPS=1` + VideoToolbox(2K) 降级运行
- 已有 `gpu_state.py` watchdog 机制，可复用

---

## 需求列表

### [P0] 双模式并行剪辑（已完成 2026-04-11）
- 状态：**已完成** ✅
- 每次剪辑都走经典模式 + 导演模式，分别输出两个版本
- DB 新增 `classic_status`（0/1/2/-1）、`publish_versions`（classic/director/both）
- `_auto_merge_group` 同时触发两条流水线；`trigger_merge` 同样
- 分组卡片：发布版本选择器（两个版本/导演版/经典版）；经典版下载按钮；导演面板始终显示
- 发布端点：按 `publish_versions` 选择视频路径，默认"两个版本"优先用导演版

### [P1] 剪辑效果测试
- 状态：通过（录像 866 处理中，内存 53% 正常）

### [P2] GPU 卸载（阶段二）
- 状态：**已完成并部署** ✅
- gpu_service.py 已部署到 `C:\Users\neo\douyin_processor\gpu_service.py`，watchdog 管理运行

### [P3] ClipQueue.vue 操作按钮（开始/重试/终止/暂停）
- 状态：**已完成** ✅
- 后端：4 个端点 `/api/clip-queue/{id}/start|cancel|pause|retry`
- 前端：等待中卡片新增 ▶/⏸/✕ 按钮；暂停中独立区块；失败录像区块+重试按钮

---

## 平台优质素材合规改造（待开发）

> 依据：`DOUYIN_VIDEO_QUALITY_GUIDE.md` — 巨量千川官方优质/低质判定标准
> 逻辑分析文档：待写（见下方 P0 说明）

### [P0] 删除违规高分关键词（`editor.py`）— **已完成 2026-04-13**

从 `_SCORES` 删除 `戴前/戴后/前后对比`（巨量千川禁止佩戴前后对比暗示改变外貌）；同步从 `_COMPARISON_KW` 删除，防止叙事槽仍选入这类片段。

---

### [P0] 调整视频时长上限（`editor.py`）— **已完成 2026-04-13**

`CLIP_MAX = 90.0`，`CLIP_MAX_V2 = 90.0`，`CLIP_MIN = 30.0`。

---

### [P1] 强制结尾号召片段（`editor.py`）— **已完成 2026-04-13**

`_select_from_valid()` convert 结尾逻辑增强：无未用 convert 段时复用任意 convert 段，只有完全没有 convert 内容时才回退到普通片段。

---

### [P1] 新增低质内容过滤规则（`editor.py`）— **已完成**（规则已在代码中）

`_REMOVE_PATTERNS` 中已包含卖惨/效果承诺/诱骗互动全部规则，无需重复添加。

---

### [P2] AI 文案禁止违规表述（`meta_generator.py`）— **已完成**（规则已在 prompt 中）

反差/前后对比已禁止（种草方案 line 79）；效果承诺已禁止（通用禁止 line 67）；产品介绍已禁止承诺性表述（line 105）；标签规则已补充（line 68）。

---

### [P2] 字幕字体大小优化 — **已完成 2026-04-13**

`editor.py` `_SUBTITLE_STYLES` 100px → 80px；`director_video.py` `_DIR_ASS_HEADER` 90px → 80px。

---

## 已完成需求

| 日期 | 需求 | 说明 |
|------|------|------|
| 2026-04-14 | CosyVoice2 TTS 修复 + 声音克隆 | `forward_one_step` attention_mask bug 修复；`inference_zero_shot` 声音克隆；`/voice-refs/upload` 上传接口；room_id 绑定机制；小圆圆不圆 v3 声音定版 |
| 2026-04-11 | 导演模式字幕关键词优化 | `editor.py` 新增 `_HIGHLIGHT_ACTION`（教程动作词）；`director_video.py` 新增 PNG 关键词金色叠加层 + `_build_director_ass`（ASS 3层渐变描边+关键词暖金高亮） |
| 2026-04-11 | 导演模式 GPU 迁移 | `director_video.py` `compose_final_video` 改提交 `/director-jobs` 到 GPU NVENC；`gpu_service/main.py` 新增 director-jobs 端点（多源 NVENC 合成 + TTS 音频替换）；`_ensure_clips_on_gpu` 自动同步源文件 |
| 2026-04-11 | 修复 trigger_merge 分发 | `main.py` `/api/groups/{id}/merge` 按 `editing_mode` 分发：导演模式→`_run_director_pipeline`，经典模式→`merge_group` |
| 2026-03-25 | ClipQueue 操作按钮 | 后端 4 端点 start/cancel/pause/retry；前端暂停中区块+失败区块+操作按钮 |
| 2026-03-25 | 阶段二 GPU 卸载 | gpu_service 新增 `/clip-jobs` + `/rembg`；editor.py 自动尝试 GPU 路径，失败回退本机 |
| 2026-03-25 | 阶段一 OOM 修复 | 分辨率 4K→2K；并发改为1；Semaphore(3)→(1)；内存监控阈值修正 |
| 2026-03-24 | 处理进度条+ETA | Groups.vue 详情表格"处理状态"列：完整状态机 + WS 推送 |
| 2026-03-24 | 自定义分组功能 | Groups.vue + Publish.vue 橙色边框；后端 custom group API |
| 2026-03-24 | 分组删除功能 | `DELETE /api/groups/{id}` |
| 2026-03-24 | 多平台发布系统 | publisher_base/douyin/kuaishou(占位)/xiaohongshu(占位)/bilibili(占位) |
| 2026-03-24 | 商品库管理 | Products.vue + 22个API端点 |
| 2026-03-24 | GPU任务队列 | gpu_state.py + ClipQueue.vue + GpuBanner.vue |
| 2026-03-24 | 背景音乐合成 | music_gen.py + 6首预置BGM |
| 2026-03-24 | 字幕烧录+关键词高亮 | editor.py 重写 |
| 2026-03-24 | 视频降噪 | denoise.py |
