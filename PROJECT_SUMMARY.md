# 项目总结报告：抖音录屏自动发布系统

---

## 版本历史

| 版本 | 日期 | 主要变更 |
|------|------|---------|
| v1.1 | 2026-03-25 | **画质过滤 + 流程优化**：低画质跳过机制、时长过短跳过、直播流分辨率监控、AI文案4方案多标签、封面暖色主题、发布分组自动合并、商品库直播间下拉、Bedrock超时90s |
| v1.0 | 2026-03-25 | **直播流质量升级**：webcast API获取原画流（ORIGIN/FULL_HD1）、fragmented MP4防止文件损坏 |
| v0.9 | 2026-03-25 | **Phase 2 GPU 卸载**：gpu_service 新增 `/clip-jobs` + `/rembg`；editor.py GPU优先路径（NVENC）+ 本机自动降级 |
| v0.8 | 2026-03-25 | **Phase 1 OOM 根治**：分辨率 4K→2K；内存监控阈值修正（5GB/4GB）；Semaphore(3)→(1)；码率 20M→8~10M |
| v0.7 | 2026-03-24 | 分组详情处理进度条+ETA（转录/剪辑全流程可视化，WS实时推送+轮询） |
| v0.6 | 2026-03-24 | 自定义分组（橙色边框，直接上传视频触发剪辑）；分组删除功能；分组管理重试按钮；批量导入视频路径 |
| v0.5 | 2026-03-24 | OOM修复（Semaphore 1、MAX_CONCURRENT_CLIPS=1、200MB合并上限、大文件自动分割）；GPU服务器启停脚本 |
| v0.4 | 2026-03-24 | 多平台发布系统（Playwright）；发布任务管理；商品库；AI 元数据生成 |
| v0.3 | 2026-03-24 | GPU任务队列 UI；背景音乐合成；字幕烧录+关键词高亮；视频降噪 |
| v0.2 | 2026-03-24 | 分组管理；合并剪辑；缩略图生成；封面合成 |
| v0.1 | 2026-03-24 | 基础直播录制；转录（faster-whisper via GPU）；自动剪辑（editor.py） |

---

## v0.7 变更说明（2026-03-24）

### 处理进度条 + 预计完成时间

#### 后端
- `main.py`：新增 `GET /api/recordings/processing-progress` 端点（注意：需放在所有 `{recording_id}` 参数路由之前，否则被 FastAPI 误匹配为整型参数）
  - 合并两路进度数据：
    - **剪辑进度**：读取 `_clip_progress[recording_id]`（已有 `pct/msg/eta_seconds/phase`）
    - **转录进度**：查 `transcribed=1` 的录像 → 用 `_job_submit_times[gpu_job_id]` + `_job_durations` 均值推算百分比和 ETA
  - 新增 import：`_job_submit_times, _job_durations` from transcribe
- `get_group` 查询：补充返回 `transcribed`、`transcribe_error` 字段；JOIN 改 LEFT JOIN 兼容自定义分组

#### 前端
- `api.js`：新增 `getProcessingProgress()`
- `Groups.vue`：
  - 新增 `progressMap` 响应式对象 `{recording_id: {pct, msg, eta_seconds, phase}}`
  - `toggleDetail()` 展开时启动 3 秒轮询（`startProgressPolling`），收起时停止
  - WS `clip_progress` 事件直接更新 `progressMap`（实时推送）
  - 处理状态列重构：完整状态机 `待转录 → 转录中进度条 → 待剪辑 → 剪辑中进度条 → 已完成↓`，失败态显示红色徽章
  - 进度条样式：紫色渐变 `width` 动画（0.4s ease）+ 右对齐百分比 + 条下方 ETA 文字
  - 新增 `formatEta(seconds)` 工具函数（`约 X分X秒`）

---

## v0.6 变更说明（2026-03-24）

### 新功能

#### 自定义分组
- **后端**
  - `db.py`：迁移新增 `clip_groups.is_custom INTEGER DEFAULT 0`
  - `main.py`：`_get_custom_room_id()` 自动创建/复用 url=`__custom__` 的虚拟房间（enabled=0，不出现在直播间列表）
  - `POST /api/groups/custom`：创建自定义分组，无需绑定直播间
  - `POST /api/groups/{id}/upload-video`：上传 .mp4 到自定义分组，写入 recordings 表（group_id 直接关联），触发转录→剪辑完整流程
  - `GET /api/groups`：INNER JOIN 改为 LEFT JOIN，兼容虚拟房间
- **前端**
  - `api.js`：新增 `createCustomGroup()`、`uploadCustomGroupVideo()`
  - `Groups.vue`：工具栏新增"+ 自定义分组"橙色按钮；自定义分组卡片橙色边框+白灰底黑字（`.group-card-custom`）；卡片底部"+ 上传视频"按钮触发文件选择并上传；分组标签替换为橙色"自定义"徽章
  - `Publish.vue`：分组选择器中自定义分组显示橙色左边框+白灰底黑字（`.group-item-custom`）

#### 分组删除
- **后端**：`DELETE /api/groups/{id}` — 解除所有关联 recordings 的 group_id（录像文件不删），再删除分组记录
- **前端**：`api.js` 新增 `deleteGroup()`；`Groups.vue` 每个分组右上角加"✕"按钮，确认后删除

### 修复
- 重启后端后 `init_db()` 自动运行迁移，`is_custom` 列写入现有 DB

---

## 验收状态

**代码审计：PASS** — 所有后端和前端文件均已正确实现，22 个 API 端点全部存在。

**发现缺陷：2项**

| # | 严重度 | 位置 | 问题 | 状态 |
|---|--------|------|------|------|
| 1 | 高 | `frontend/src/composables/toast.js` | `useToast()` 返回 `showToast` 命名与调用方不一致 | **已确认无误**（文件已正确使用 `showToast`） |
| 2 | 中 | Python 环境 | `playwright` 未安装，发布功能无法运行 | 需手动安装 |

**安装 Playwright：**
```bash
cd /Users/claw/work/douyin-recorder/backend
pip install playwright
playwright install chromium
```

---

## 架构总览

```
products 表 ──┐
              ├── 关键词匹配 ──→ publish_tasks 表 ──→ 各平台 Publisher
clip_groups ──┘                                       (Playwright)
     ↑
  LLM元数据生成 (Bedrock, 复用 analyzer.py 模式)
```

---

## 数据库扩展

### `products`（小黄车商品库）
```sql
id INTEGER PK
platform TEXT DEFAULT 'douyin'
product_id TEXT          -- 抖音商品ID
product_name TEXT
product_url TEXT
keywords TEXT            -- 逗号分隔匹配关键词，如"假发,Bob,黑色"
enabled INT DEFAULT 1
created_at TIMESTAMP
```

### `publish_accounts`（平台账号/Cookie）
```sql
id INTEGER PK
platform TEXT            -- douyin/kuaishou/xiaohongshu/bilibili
account_name TEXT
cookie_file TEXT
enabled INT DEFAULT 1
created_at TIMESTAMP
```

### `publish_tasks`（发布任务）
```sql
id INTEGER PK
group_id INT FK(clip_groups)
platform TEXT
account_id INT FK(publish_accounts)
status TEXT DEFAULT 'pending'  -- pending/scheduled/publishing/done/failed
scheduled_at TIMESTAMP
title TEXT
description TEXT
tags TEXT
product_id INT FK(products)
video_path TEXT
published_at TIMESTAMP
error_msg TEXT
created_at TIMESTAMP
```

---

## API 端点（22个）

### 商品管理
- `GET /api/products` — 列表（支持 keyword 搜索）
- `POST /api/products` — 新增单个商品
- `POST /api/products/bulk` — 批量导入
- `PATCH /api/products/{id}` — 编辑
- `DELETE /api/products/{id}` — 删除

### 账号管理
- `GET /api/publish-accounts` — 列表
- `POST /api/publish-accounts` — 新增账号
- `DELETE /api/publish-accounts/{id}` — 删除
- `POST /api/publish-accounts/{id}/login` — Playwright 扫码登录

### 发布任务
- `GET /api/publish-tasks` — 列表
- `POST /api/publish-tasks` — 创建任务（支持 auto_meta=true）
- `GET /api/publish-tasks/{id}` — 详情
- `DELETE /api/publish-tasks/{id}` — 取消
- `POST /api/publish-tasks/{id}/retry` — 重试失败任务

### 商品自动匹配
- `POST /api/groups/{id}/match-product` — 根据 group 关键词自动匹配商品

---

## 后端文件清单

| 文件 | 说明 |
|------|------|
| `backend/db.py` | 新增 3 张表 |
| `backend/models.py` | 新增 Pydantic 模型 |
| `backend/meta_generator.py` | Bedrock LLM 生成标题/描述/标签 |
| `backend/publisher_base.py` | 抽象基类 |
| `backend/publisher_douyin.py` | Playwright 抖音完整发布流程 |
| `backend/publisher_kuaishou.py` | 占位（NotImplementedError） |
| `backend/publisher_xiaohongshu.py` | 占位 |
| `backend/publisher_bilibili.py` | 占位 |
| `backend/publish_scheduler.py` | 定时调度（60秒轮询） |
| `backend/main.py` | 新增路由 + 启动调度器 |

## 前端文件清单

| 文件 | 说明 |
|------|------|
| `frontend/src/views/Products.vue` | 商品库页面（列表/新增/批量导入/搜索） |
| `frontend/src/views/Publish.vue` | 发布管理页面（任务创建/列表/AI生成元数据） |
| `frontend/src/App.vue` | 导航栏新增商品库和发布入口 |
| `frontend/src/api.js` | 新增所有 API 调用函数 |

---

## 商品关键词匹配逻辑

优先级：
1. 精确匹配：`product.keywords` 中有词 ∈ `{wig_model, wig_color}`
2. 模糊匹配：`product.keywords` 包含 `wig_model` 的子串
3. 无匹配：返回 `None`，前端提示手动选择

---

## Cookie 登录流程

1. 用户点击"登录"按钮
2. 后端调用 `POST /api/publish-accounts/{id}/login`
3. Playwright 启动有头浏览器，打开平台登录页
4. 用户手动扫码完成登录
5. 保存 cookies 至 `~/.douyin-publisher/cookies/{platform}_{account_id}.json`
6. 后续发布加载此 cookies，无头模式运行

---

## 验证命令

```bash
# 1. 确认DB表存在
sqlite3 /Users/claw/work/douyin-recorder/douyin.db ".tables"
# 期望包含: products  publish_accounts  publish_tasks

# 2. 导入测试商品
curl -X POST http://localhost:8899/api/products/bulk \
  -H "Content-Type: application/json" \
  -d '[{"product_id":"123","product_name":"假发测试","keywords":"假发,Bob,黑色"}]'

# 3. 测试搜索
curl "http://localhost:8899/api/products?keyword=Bob"

# 4. 创建发布账号
curl -X POST http://localhost:8899/api/publish-accounts \
  -H "Content-Type: application/json" \
  -d '{"platform":"douyin","account_name":"测试账号"}'

# 5. 创建发布任务（需 merge_status=2 的 clip_group）
curl -X POST http://localhost:8899/api/publish-tasks \
  -H "Content-Type: application/json" \
  -d '{"group_id":1,"platform":"douyin","title":"测试标题","auto_meta":false}'

# 6. 前端 toast 验证
# 浏览器打开 http://localhost:5173
# 商品库页面新增商品 → 确认绿色 toast "商品已添加"
# 发布页面创建任务 → 确认 toast 正常显示
```

---

## v0.8 变更说明（2026-03-25）—— Phase 1 OOM 根治

### 问题背景

Mac M2 8GB 统一内存在原配置下内存占用等效 ~45GB（大量 Swap），macOS 弹出"应用内存不足"强制终止。

### 根因

`MAX_CONCURRENT_CLIPS=2` × 每任务 `Semaphore(3)` anime/zoom 帧提取 = 最多 6 路并发 4K VideoToolbox 进程，每路 ~1~2GB Metal buffer（不可 Swap），严重超出 8GB 物理内存。内存监控阈值 `MEM_WARN_GB=20` 在 8GB 机器上永远无法触发，形同虚设。

### 改动文件

| 文件 | 改动 |
|------|------|
| `backend/transcribe.py:56` | `MAX_CONCURRENT_CLIPS` 默认值 `"2"` → `"1"` |
| `backend/editor.py:281-282` | `OUT_W/OUT_H` 4K(2160×3840) → 2K(1080×1920) |
| `backend/editor.py:866` | `sem_frames` Semaphore(3) → Semaphore(1) |
| `backend/editor.py:925` | `sem_zoom` Semaphore(3) → Semaphore(1) |
| `backend/editor.py` 多处 | 预编码码率 20M→10M，xfade 15M→8M，final 20M→10M |
| `backend/main.py:78-80` | `MEM_WARN_GB` 20→5，`MEM_RECOVER_GB` 17→4，`INTERVAL` 30→10 |
| `backend/thumbnail.py:189,225` | 帧提取与 PIL 合成尺寸 4K→2K |

### 效果（录像 866 实测）

- RAM 峰值：~45GB 等效 → **4.1GB / 8.6GB (63%)**
- Swap：~45GB → **0.9GB**
- ffmpeg 进程数：最多 6 → **1**（串行）

---

## v0.9 变更说明（2026-03-25）—— Phase 2 GPU 卸载

### 架构

```
Mac（M2 8GB）                          GPU Server（RTX 4080S 16GB，Windows）
──────────────────────────────         ──────────────────────────────────────
parse SRT → score → select segs  ───→  POST /clip-jobs
build ASS subtitles               ←──  GET  /clip-jobs/{id}   (轮询进度)
download clip.mp4                 ←──  GET  /clip-jobs/{id}/mp4
generate_thumbnail (PIL overlay)       ─ NVENC preprocess + xfade merge
_prepend_thumbnail                     ─ subtitle burn (libass+NVENC)
                                       ─ thumbnail frame extract

GPU rembg (CUDA):
  _gen_person_frames → POST /rembg ───→ U2Net CUDA (<0.5s)
                                  ←──  PNG with background removed
```

### 降级策略

- GPU 服务离线（`is_online()=False`）→ 自动跳过 GPU 路径，走本机 VideoToolbox 2K 流水线
- GPU clip job 失败/超时（25min）→ 同上回退，日志记录 warning

### 改动文件

| 文件 | 改动 |
|------|------|
| `gpu_service/main.py` | 新增 `POST /clip-jobs`、`GET /clip-jobs/{id}`、`GET /clip-jobs/{id}/mp4`、`GET /clip-jobs/{id}/thumb`、`POST /rembg`；NVENC 流水线 `_do_clip_job`；DB 持久化 `clip_jobs` 表；Windows 路径适配 |
| `backend/editor.py` | 新增 `_edit_via_gpu()`；`edit_recording()` 增加 `room_id` 参数，GPU 优先路径；`_gen_person_frames` GPU rembg 优先 |
| `backend/transcribe.py` | DB 查询增加 `r.room_id`，传递给 `edit_recording()` |
| `gpu_service/requirements.txt` | 新增 `pydantic>=2.0.0`、`rembg>=2.0.50` |

### 部署说明

- GPU 服务部署路径：`C:\Users\neo\douyin_processor\gpu_service.py`
- 由 Watchdog 管理（`watchdog_config.json` 中 `"cmd": ["python", "gpu_service.py"]`）
- 新录像上传后存储于 `C:\Users\neo\douyin_recordings\{room_id}\{filename}`
- 旧 UUID 方式存储的录像（部署前）走本机降级路径（`local_deleted=0`，本机 MP4 仍存在）

### GPU 资源评估（同时运行）

```
Whisper large-v3：   ~3 GB VRAM（转录时）
ComfyUI AnythingV5：  ~6~8 GB VRAM（动漫帧时）
NVENC ffmpeg：         0 GB VRAM（独立硬件单元）
rembg CUDA：         ~0.5 GB VRAM
─────────────────────────────────────
最坏并发：            ~11 GB < 16 GB ✅
```

---

## v1.0 变更说明（2026-03-25）

### 直播流质量升级：Webcast API

#### 问题
原来用 HTML 正则提取直播流 URL，只能获取低画质流，无法获取原画（ORIGIN）。

#### 方案
`backend/douyin_live.py` 全面重写：
- `_load_auth_cookies()`：自动加载 `~/.douyin-publisher/cookies/douyin_*.json`（Playwright 格式），转换为 httpx cookies
- `_fetch_webcast_stream(room_id)`：调用 `https://live.douyin.com/webcast/room/web/enter/`，解析 `flv_pull_url` 字典，按优先级选最高画质
  - 质量优先级：`ORIGIN(6) > FULL_HD1(5) > UHD(4) > HD1(3) > SD1(2) > LD1(1)`
- `get_stream_url()`：先获取 ttwid cookie → 调 webcast API → fallback 到 HTML 正则

#### 录制效果验证
- 房间 808798367656：获得 `FULL_HD1`，录制结果 1088×1920 @ 3.9Mbps，509MB/18分钟 ✅

### Fragmented MP4 防止文件损坏

#### 问题
直播结束时 ffmpeg 被强制终止，moov atom 未写入，导致文件不可读（"moov atom not found"）。

#### 方案
`backend/recorder.py`：将 `-movflags +faststart` 改为 `-movflags frag_keyframe+empty_moov+default_base_moof`，每个关键帧写一次 moov，流式可读。

---

## v1.1 变更说明（2026-03-25）

### 低画质录像过滤机制

#### 背景
历史积累了大量低于 720p 的录像（共 135 条），一直占用剪辑队列并反复失败。

#### 方案
**`backend/transcribe.py`**：
- 常量 `MIN_RECORDING_HEIGHT = 720`
- `_run_editor()` 入口处增加分辨率检查（ffprobe），低于 720p 设 `skip_reason='分辨率过低（Xp < 720p）'`，`clipped=-1` 跳过
- 常量 `MIN_RECORDING_DURATION = 30`
- 新增时长检查，短于 30 秒设 `skip_reason='录像时长过短（Xs）'`，避免"bye bye"类末尾片段失败

**`backend/db.py`**：
- 新增迁移：`ALTER TABLE recordings ADD COLUMN skip_reason TEXT`

**`backend/main.py`**：
- `_STATUS_WHERE["clip_failed"]` 等条件加 `AND (r.skip_reason IS NULL OR r.skip_reason = '')`，过滤已跳过记录，防止出现在重试队列

**历史数据清理**：
- 已取消/标记 7 个排队中低画质作业
- 已批量标记 135 条低画质 + 4 条损坏录像的 `skip_reason`

### 直播间分辨率实时监控

**`backend/monitor.py`**：
- 新增 `_resolution_warnings: Dict[int, Optional[str]]`
- `_check_stream_resolution(room_id, filename)`：录制开始 20 秒后用 ffprobe 检测分辨率，低于 720p 设警告文字
- `_on_segment_start()` 异步触发检测任务
- `get_status()` 返回 `resolution_warning` 字段

**`frontend/src/views/Dashboard.vue`**：
- 房间卡片增加黄色警告条，实时显示 `⚠ 直播间画质过低：WxH（低于720P）`

**`frontend/src/views/History.vue`**：
- 有 `skip_reason` 的失败录像显示 `⚠ 已跳过` badge，而非"重试"按钮

### AI 文案多方案生成

**`backend/meta_generator.py`**：
- `_META_PROMPT` 改为生成 4 套方案：种草、催单、产品介绍、教学
- 催单方案包含"直播间同价，宝子们点左下方小黄车就可以下单"
- 返回格式：`{"schemes": [{type, title, description, tags}, ...]}`，max_tokens=2400
- Bedrock httpx 超时从 30s → 90s（修复4方案生成超时失败）

**`frontend/src/views/Publish.vue`**：
- `metaSchemes` / `selectedScheme` / `currentScheme` refs
- 方案 Tab 选择器 + 预览面板
- 分组列表悬停操作：▶ 预览（视频弹窗）、↺ 重剪（重剪反馈）、✕ 删除

### 封面图暖色主题升级

**`backend/thumbnail.py`**：
- `_THEMES` 全部替换为暖色系：樱花粉、蜜桃阳光、糖果天蓝、暖柠檬黄、春日薄荷
- 底部黑色遮罩 alpha 从 200 降至 140，覆盖范围从 2/3 缩至 3/4

**`backend/comfyui_client.py`**：
- `_POSITIVE_BASE` 加入：`cheerful bright lighting, sunny atmosphere, warm golden light, happy joyful expression`
- `_NEGATIVE` 加入：`dark, gloomy, moody, shadow, low contrast, desaturated`

### 发布分组自动合并

**`backend/transcribe.py`**：
- `_do_edit()` 成功后调用 `asyncio.create_task(_maybe_auto_merge(recording_id))`
- `_maybe_auto_merge()`：检查同分组所有录像是否均 `clipped=2`，是则自动触发 `merge_group(group_id)`
- 不再需要用户手动点击"合并剪辑"

**已手动触发合并**：23 个积压未合并的分组已全部触发合并完成。

### 商品库直播间下拉修改

**`frontend/src/views/Products.vue`**：
- 直播间列改为 `<select>` 下拉框，可实时切换关联直播间
- `changeRoom(p, roomId)` 调用 `updateProduct(p.id, { room_id })` 保存

---

## 回滚指南

### 快速回滚到上个版本（v0.9）
```bash
git checkout 4273069 -- backend/ frontend/src/ gpu_service/
```

### 快速回滚特定文件
```bash
# 回滚封面主题（如不喜欢新配色）
git checkout 4273069 -- backend/thumbnail.py backend/comfyui_client.py

# 回滚流质量逻辑（如 webcast API 有问题）
git checkout 4273069 -- backend/douyin_live.py backend/recorder.py

# 回滚 AI 文案（如多方案格式有兼容问题）
git checkout 4273069 -- backend/meta_generator.py

# 回滚 skip_reason 逻辑（谨慎：需同步回滚 DB schema）
git checkout 4273069 -- backend/transcribe.py backend/main.py
```

### DB schema 回滚（如需去掉 skip_reason 列）
SQLite 不支持 DROP COLUMN（v3.35+才支持），如需彻底回滚：
```bash
sqlite3 douyin.db "ALTER TABLE recordings DROP COLUMN skip_reason;"
# 或重建表（保留数据）
```
