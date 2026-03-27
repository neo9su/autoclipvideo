# 需求清单 — douyin-recorder

> 本文件由 Claude Code 自动维护。每次对话结束前回写，新对话开始时优先读取。
> 最后更新：2026-03-27

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

### [P0] 删除违规高分关键词（`editor.py`）

**问题**：`_SCORES` 中「戴之前(8分)」「戴之后(8分)」「对比(8分)」「变美(8分)」被高分加权，优先选入这类片段。巨量千川明确规定**不得展示佩戴前后对比来暗示改变外貌**，否则判定低质素材并降低曝光。

**改动**：从 `_SCORES` 删除以上 4 个关键词。

---

### [P0] 调整视频时长上限（`editor.py`）

**问题**：`CLIP_MAX=240s`（4分钟），远超平台推荐的 15–60s。长视频完播率极低，直接影响优质素材评分。

**改动**：`CLIP_MAX = 60.0`（原 240.0），`CLIP_MIN = 30.0`（原 46.0）。

---

### [P1] 强制结尾号召片段（`editor.py`）

**问题**：`convert` 分类片段（点购物车/加购/运费险等）仅占 15% 预算，内容不足时被丢弃，导致视频无 CTA 结尾。平台优质标准要求结尾必须有明确购买引导。

**改动**：`_select_from_valid()` 中 convert 段改为**强制存在**，固定排在 assembled 末位。

---

### [P1] 新增低质内容过滤规则（`editor.py`）

**新增 `_REMOVE_PATTERNS`**：
- 卖惨营销：`快撑不下去` `房租到期` `老板亏本` `清仓处理`
- 效果承诺：`保证变美` `显年轻\d+岁` `遮住所有` `彻底解决`
- 诱骗互动：`点赞送礼` `评论抽奖` `转发有惊喜`

---

### [P2] AI 文案禁止违规表述（`meta_generator.py`）

**问题**：种草方案「反差/前后对比」切入角度暗示效果对比，违规；催单方案「想要的宝子抓紧」有催单感。

**改动**：
- 删除「反差/前后对比」切入角度
- 产品介绍方案新增禁止规则：不使用效果承诺语句
- 标签要求补充：只使用假发品类垂直标签，禁止蹭热点话题

---

### [P2] 字幕字体大小优化（`editor.py`）

**问题**：当前字体 92–102px（1440×2560 分辨率），存在"大字报"风险，平台将大面积文字覆盖判定为低质。

**改动**：`_SUBTITLE_STYLES` 字体大小全部降至 72–88px。

---

## 已完成需求

| 日期 | 需求 | 说明 |
|------|------|------|
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
