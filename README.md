# 抖音录屏自动发布系统

> **v1.8.0** — 录屏剪辑 → AI分析 → 自动发布的全流程工具

直播录屏 → GPU 转录 → 智能剪辑（GPU NVENC / 本机 VideoToolbox 双路）→ Bedrock AI 分析 → 多平台自动发布

---

## 硬件环境

| 节点 | 硬件 | 职责 |
|------|------|------|
| 本机 | M2 8GB 统一内存 | 编排 / FastAPI 后端 / 前端 / 发布（Playwright） |
| GPU 服务器 | RTX 4080 SUPER 16GB，`10.190.0.203` | Whisper 转录(:8877) + ComfyUI(:8188) + Watchdog(:8878) |

---

## 快速开始

### 环境要求

- Python 3.11+（本机）、Python 3.13（GPU 服务器）
- Node.js 18+
- ffmpeg / ffprobe（本机）
- AWS Bedrock 访问权限（AI 分析和元数据生成）

### 安装

```bash
# 后端
cd backend
pip install -r ../requirements.txt
pip install playwright && playwright install chromium

# 前端
cd frontend
npm install
```

### 启动

```bash
# 后端（端口 8899）
cd backend
nohup uvicorn main:app --host 0.0.0.0 --port 8899 > /tmp/douyin_backend.log 2>&1 &

# 前端（端口 5173）
cd frontend
npm run dev
```

访问 http://localhost:5173

---

## 功能模块

### 直播录制
- 监控多个直播间，自动录制保存 MP4 片段
- 小片段自动合并（≤200MB 合并阈值，大文件自动分割）

### GPU 转录
- 上传 MP4 至 GPU 服务器（10.190.0.203:8877）
- faster-whisper large-v3 CUDA 转录，生成 SRT 字幕

### 智能剪辑
- 解析 SRT → 评分选段 → xfade 树形合并 → 字幕烧录 → BGM 混音 → 封面合成
- **GPU 路径（NVENC）**：片段已在 GPU 服务器时自动走 NVENC 编码，零 Mac 内存压力
- **本机降级**：GPU 离线时回退至 VideoToolbox 2K（1080×1920，10Mbps）
- 动漫过渡帧（ComfyUI img2img）、缩放冲击、背景去除（rembg CUDA/CPU）

### AI 分析（Bedrock）
- 分析假发颜色、款式（`wig_model` / `wig_color`）
- 识别促销场景标签，生成发布元数据

### 商品库（小黄车）
- 管理抖音商品（商品ID/名称/关键词）
- 关键词自动匹配视频组

### 自动发布
- 多平台：抖音（完整）/ 快手 / 小红书 / B站（占位）
- Playwright 自动化：上传视频、填写元数据、挂商品、发布
- 定时发布 + AI 元数据生成（Bedrock LLM）
- AI 元数据遵循巨量千川优质素材规范（详见 [DOUYIN_VIDEO_QUALITY_GUIDE.md](DOUYIN_VIDEO_QUALITY_GUIDE.md)）

---

## 数据库

SQLite，路径：`douyin.db`

| 表 | 说明 |
|----|------|
| `recordings` | 录屏文件（转录状态、剪辑状态） |
| `rooms` | 直播间配置 |
| `clip_groups` | 视频片段组 |
| `recording_clips` | 多变体剪辑结果 |
| `products` | 商品库 |
| `publish_accounts` | 平台账号 |
| `publish_tasks` | 发布任务 |

---

## API

后端启动后访问 http://localhost:8899/docs 查看完整 Swagger 文档。

| 模块 | 端点 |
|------|------|
| 录屏 | `GET /api/recordings` |
| 剪辑队列 | `GET /api/clip-queue` |
| GPU 状态 | `GET /api/gpu/status` |
| 分析 | `POST /api/groups/{id}/analyze` |
| 商品 | `GET/POST /api/products` |
| 发布账号 | `GET/POST /api/publish-accounts` |
| 发布任务 | `GET/POST /api/publish-tasks` |

---

## 目录结构

```
douyin-recorder/
├── backend/
│   ├── main.py                  # FastAPI 入口 + 所有路由
│   ├── editor.py                # 智能剪辑（GPU/本机双路）
│   ├── transcribe.py            # 转录调度 + 剪辑派发
│   ├── sync.py                  # GPU 服务上传
│   ├── gpu_state.py             # GPU Watchdog 监控
│   ├── thumbnail.py             # 动漫封面合成（PIL + ComfyUI）
│   ├── comfyui_client.py        # ComfyUI img2img 客户端
│   ├── denoise.py               # noisereduce 音频降噪
│   ├── analyzer.py              # Bedrock AI 分析
│   ├── meta_generator.py        # LLM 发布元数据生成
│   ├── music_gen.py             # BGM 生成
│   ├── segment_merger.py        # 片段合并（200MB 阈值）
│   ├── publisher_base.py        # Publisher 抽象基类
│   ├── publisher_douyin.py      # 抖音 Playwright 发布
│   └── publish_scheduler.py    # 定时调度
├── gpu_service/
│   └── main.py                  # GPU 服务（转录 + clip-jobs + rembg）
│                                # 部署至 C:\Users\neo\douyin_processor\gpu_service.py
├── frontend/
│   └── src/
│       ├── views/               # Groups / Products / Publish / ClipQueue
│       ├── App.vue
│       └── api.js
├── recordings/                  # 本机录屏存储
├── douyin.db                    # SQLite 数据库
├── demander.md                  # 需求跟踪（Claude Code 自动维护）
├── DOUYIN_VIDEO_QUALITY_GUIDE.md  # 巨量千川优质/低质素材标准（假发行业）
└── PROJECT_SUMMARY.md           # 版本历史与变更详情
```

---

## 配置

```bash
# AWS Bedrock（AI 分析）
export AWS_BEARER_TOKEN_BEDROCK=<your-token>
export AWS_REGION=us-east-1

# GPU 服务地址（可选，默认 10.190.0.203:8877）
export GPU_SERVICE_URL=http://10.190.0.203:8877

# 内存限制（默认已针对 M2 8GB 优化）
export MEM_WARN_GB=5
export MAX_CONCURRENT_CLIPS=1
```

---

## 发布功能首次使用

1. "账号管理"添加账号 → 点"登录"扫码授权
2. "商品库"导入商品（可批量粘贴 JSON）
3. 确保视频已完成转录+剪辑（`clipped=2`）
4. "发布"页面选择视频 → 选平台/账号 → "AI生成"或手动填写 → 发布
