# 抖音录屏自动发布系统

录屏剪辑 → AI分析 → 自动发布的全流程工具，支持抖音/快手/小红书/B站多平台发布，挂小黄车商品，Bedrock LLM 生成标题/描述/标签。

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+
- AWS Bedrock 访问权限（用于 AI 分析和元数据生成）

### 安装

```bash
# 后端
cd backend
pip install -r requirements.txt
pip install playwright
playwright install chromium

# 前端
cd frontend
npm install
```

### 启动

```bash
# 后端（默认端口 8899）
cd backend
python main.py

# 前端（默认端口 5173）
cd frontend
npm run dev
```

访问 http://localhost:5173

---

## 功能模块

### 录屏管理
- 监控指定目录，自动识别新录屏文件
- 按 session 组织录屏片段

### AI 分析（Bedrock）
- 分析假发颜色、款式（wig_model / wig_color）
- 生成 SRT 字幕
- 识别场景标签

### 视频合并
- 将同一 session 的片段合并为完整视频
- FFmpeg 处理

### 商品库（小黄车）
- 管理抖音商品信息（商品ID/名称/关键词）
- 关键词自动匹配 clip_group 的 wig_model/wig_color
- 支持批量导入（JSON/CSV）

### 自动发布
- 多平台支持：抖音（完整实现）/ 快手 / 小红书 / B站（占位）
- Playwright 自动化：上传视频、填写元数据、挂商品、发布
- 定时发布：设定时间自动触发
- AI 元数据：Bedrock LLM 自动生成标题/描述/话题标签
- Cookie 登录：有头浏览器扫码，后续无头运行

---

## 数据库

SQLite，默认路径：`douyin.db`

主要表：
- `recordings` — 录屏文件
- `clip_groups` — 视频片段组
- `products` — 商品库
- `publish_accounts` — 平台账号
- `publish_tasks` — 发布任务

---

## API

后端运行后，访问 http://localhost:8899/docs 查看完整 Swagger 文档。

主要端点：

| 模块 | 端点 |
|------|------|
| 录屏 | `GET /api/recordings` |
| 分析 | `POST /api/groups/{id}/analyze` |
| 合并 | `POST /api/groups/{id}/merge` |
| 商品 | `GET/POST /api/products` |
| 账号 | `GET/POST /api/publish-accounts` |
| 发布 | `GET/POST /api/publish-tasks` |
| 匹配 | `POST /api/groups/{id}/match-product` |

---

## 目录结构

```
douyin-recorder/
├── backend/
│   ├── main.py                  # FastAPI 入口 + 所有路由
│   ├── db.py                    # 数据库初始化
│   ├── models.py                # Pydantic 模型
│   ├── analyzer.py              # Bedrock AI 分析
│   ├── meta_generator.py        # LLM 生成发布元数据
│   ├── publisher_base.py        # Publisher 抽象基类
│   ├── publisher_douyin.py      # 抖音 Playwright 发布
│   ├── publisher_kuaishou.py    # 快手（占位）
│   ├── publisher_xiaohongshu.py # 小红书（占位）
│   ├── publisher_bilibili.py    # B站（占位）
│   └── publish_scheduler.py    # 定时调度（60s 轮询）
├── frontend/
│   └── src/
│       ├── views/
│       │   ├── Products.vue     # 商品库页面
│       │   └── Publish.vue      # 发布管理页面
│       ├── App.vue              # 导航
│       ├── api.js               # API 调用封装
│       └── composables/
│           └── toast.js         # Toast 通知
├── recordings/                  # 录屏存储目录
├── douyin.db                    # SQLite 数据库
└── README.md
```

---

## 首次使用发布功能

1. 在"账号管理"添加账号，点击"登录"，扫码完成授权
2. 在"商品库"导入商品（可批量粘贴 JSON）
3. 确保视频已分析并合并（`merge_status=2`）
4. 在"发布"页面选择视频片段 → 选平台/账号 → 点"AI生成"或手动填写元数据 → 发布

---

## 配置

AWS Bedrock 需要在环境变量中配置：

```bash
export AWS_BEARER_TOKEN_BEDROCK=<your-token>
export AWS_REGION=us-east-1
```
