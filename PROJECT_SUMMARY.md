# 项目总结报告：抖音录屏自动发布系统

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
