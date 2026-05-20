# AutoClipVideo — 抖音直播录屏全自动剪辑发布系统

> **v2.0.0** — 直播录屏 → GPU 转录 → 三模式智能剪辑 → AI 文案 → 唇型同步 → 自动发布

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green.svg)](https://fastapi.tiangolo.com)
[![Vue 3](https://img.shields.io/badge/Vue-3-brightgreen.svg)](https://vuejs.org)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://docker.com)

---

## 功能亮点

- 🎥 **多直播间同时录制**，自动分段、合并
- 🎤 **GPU Whisper 转录**（faster-whisper large-v3，RTX 4080S）
- ✂️ **三模式剪辑**：经典版 / 导演版（AI 文案 + TTS + 唇型同步）/ 自编版
- 🤖 **AI 文案生成**（AWS Bedrock Claude）+ 人工审核编辑
- 👄 **Lip Sync 唇型同步**（Wav2Lip，可选）
- 📱 **Playwright 自动发布**：抖音 / 快手 / 小红书
- 🛒 **商品库管理**：自动匹配小黄车
- 📊 **GPU 状态监控** + 自动重启 + 告警通知

---

## 架构

```
┌─────────────────────────────────────────────────────────┐
│  Frontend (Vue 3)          http://localhost:5173         │
├─────────────────────────────────────────────────────────┤
│  Backend (FastAPI)         http://localhost:8899         │
│  ├── 录制监控 (ffmpeg)                                    │
│  ├── 转录调度 + 剪辑派发                                   │
│  ├── 导演模式 (AI脚本 + TTS + 视频合成)                     │
│  ├── 发布调度 (Playwright)                                │
│  └── WebSocket 实时推送                                   │
├─────────────────────────────────────────────────────────┤
│  GPU Service               http://gpu:8877              │
│  ├── Whisper 转录                                        │
│  ├── NVENC 视频编码                                       │
│  ├── Wav2Lip 唇型同步 (可选)                               │
│  └── ComfyUI img2img (动漫过渡帧)                          │
├─────────────────────────────────────────────────────────┤
│  Watchdog                  http://gpu:8878              │
│  └── GPU 服务健康监控 + 自动重启                             │
└─────────────────────────────────────────────────────────┘
```

---

## 快速开始

### Docker 部署（推荐）

```bash
# 克隆仓库
git clone https://github.com/neo9su/autoclipvideo.git
cd autoclipvideo

# 配置环境变量
cp .env.example .env
# 编辑 .env 填写 AWS_BEARER_TOKEN_BEDROCK、GPU_SERVICE_URL 等

# 启动
docker compose up -d

# 访问
# 前端: http://localhost:5173
# 后端 API: http://localhost:8899/docs
```

### 手动部署

```bash
# 后端
cd backend
pip install -r ../requirements.txt
pip install playwright && playwright install chromium

# 前端
cd frontend
npm install && npm run build

# 启动后端（服务前后端静态文件）
cd backend
uvicorn main:app --host 0.0.0.0 --port 8899
```

---

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `GPU_SERVICE_URL` | GPU 转录服务地址 | `http://10.190.0.203:8877` |
| `COMFYUI_URL` | ComfyUI 地址 | `http://10.190.0.203:8188` |
| `WATCHDOG_URL` | Watchdog 地址 | `http://10.190.0.203:8878` |
| `AWS_BEARER_TOKEN_BEDROCK` | Bedrock AI 凭证 | — |
| `AWS_REGION` | AWS 区域 | `us-east-1` |
| `MAX_CONCURRENT_CLIPS` | 并发剪辑数 | `1` |
| `MEM_WARN_GB` | 内存告警阈值 | `5` |
| `COSYVOICE_URL` | CosyVoice2 TTS 地址 | GPU 服务内置 |

---

## 剪辑模式

### 经典版
原始直播素材 → SRT 评分选段 → xfade 合并 → 字幕 + BGM → 色调增强 + 锐化

### 导演版
1. AI 生成文案脚本（产品细节 + 使用方法为主）
2. **人工审核/编辑文案**（可重新生成）
3. CosyVoice2 TTS 合成配音
4. 语义匹配录像片段（连续讲解不切断）
5. GPU 合成（NVENC + xfade + 字幕）
6. **Lip Sync 唇型同步**（可选，Wav2Lip）

### 自编版
手动编写文案 → TTS → 视频合成

---

## GPU 服务部署

GPU 服务运行在 Windows + NVIDIA GPU 环境：

```bash
# 在 GPU 服务器上
cd C:\Users\neo\douyin_processor
pip install faster-whisper torch torchvision torchaudio
pip install fastapi uvicorn aiofiles

# 启动
python gpu_service.py
```

### Lip Sync 部署（可选）

```bash
# 在 GPU 服务器上
mkdir C:\Users\neo\lipsync\models
# 下载模型 wav2lip_gan.pth (~435MB) 到 models/
# 部署 lipsync_infer.py 到 C:\Users\neo\lipsync\
# 模型存在时自动启用，删除模型即关闭
```

---

## 项目结构

```
autoclipvideo/
├── backend/
│   ├── main.py                  # FastAPI 入口
│   ├── monitor.py               # 直播间监控 + 录制
│   ├── recorder.py              # ffmpeg 录制器
│   ├── transcribe.py            # 转录调度 + 剪辑派发
│   ├── editor.py                # 经典剪辑引擎
│   ├── director_script.py       # 导演模式 AI 文案
│   ├── director_video.py        # 导演模式视频合成
│   ├── director_matcher.py      # 语义匹配录像片段
│   ├── voice_director.py        # TTS 配音管理
│   ├── analyzer.py              # Bedrock AI 分析
│   ├── sync.py                  # GPU 文件上传
│   ├── gpu_state.py             # GPU 可用性监控
│   ├── publisher_douyin.py      # 抖音自动发布
│   ├── publish_scheduler.py     # 发布定时调度
│   └── api_v2.py                # 导演模式 API
├── gpu_service/
│   ├── main.py                  # GPU 服务 (Whisper + NVENC + LipSync)
│   ├── lipsync_infer.py         # Wav2Lip 推理脚本
│   └── deploy_lipsync.bat       # Lip Sync 部署脚本
├── frontend/
│   ├── src/
│   │   ├── views/               # Vue 页面组件
│   │   └── App.vue
│   ├── package.json
│   └── vite.config.js
├── docker-compose.yml           # Docker 编排
├── Dockerfile                   # 后端 + 前端容器
├── requirements.txt             # Python 依赖
├── .env.example                 # 环境变量模板
└── README.md
```

---

## API 文档

启动后访问 http://localhost:8899/docs（Swagger UI）

| 模块 | 端点 | 说明 |
|------|------|------|
| 录屏 | `GET /api/recordings` | 录屏列表 |
| 转录 | `GET /api/transcribe-queue` | 转录队列状态 |
| 分组 | `GET /api/groups` | 视频分组 |
| 导演 | `POST /api/v2/director/generate-script` | 生成 AI 文案 |
| 导演 | `POST /api/v2/director/update-script` | 编辑/审核文案 |
| 导演 | `POST /api/v2/director/generate-voiceover` | 生成 TTS 配音 |
| 导演 | `POST /api/v2/director/compose-video` | 合成视频 |
| GPU | `GET /api/gpu/status` | GPU 服务状态 |
| 商品 | `GET/POST /api/products` | 商品 CRUD |
| 发布 | `GET/POST /api/publish-tasks` | 发布任务 |

---

## 版本历史

| 版本 | 日期 | 说明 |
|------|------|------|
| v2.0.0 | 2026-05-20 | Docker 部署 + Lip Sync + 文案审核 + 经典画质提升 |
| v1.9.1 | 2026-05-08 | Watchdog GPU 占用率监测 |
| v1.9.0 | 2026-04-27 | 新潮趋势评分 + 种草文案方案 |
| v1.8.2 | 2026-04-27 | KUKU 人设 + 信息深度 + 视觉质量评分 |
| v1.8.0 | 2026-04-26 | 发布自动重试 + GPU 告警 + AI 文案随机化 |
| v1.7.0 | 2026-04-26 | 视频时长校验 + SRT 合并 |
| v1.6.0 | 2026-04-21 | 过期重排期 + 文案重生成 + 批量排期修复 |
| v1.5.0 | 2026-04-21 | SQLite 并发锁修复 + 自编版 |
| v1.4.0 | 2026-04-16 | 巨量千川合规改造 |

---

## License

Private repository. All rights reserved.
