# 镜头与场景变化能力评估

> 基于抖音反馈 "镜头太单一，增加特写展示网底和发丝细节，用分镜切换佩戴步骤，配合轻微推拉运镜，让画面更生动"
> 评估日期：2026-07-01

---

## 一、现状：我们已经有什么

### 1. 经典版剪辑（`editor.py`）

| 能力 | 实现 | 效果 |
|------|------|------|
| **镜头分割** | SRT 分段评分 → 选 4-8 段 → 切 concat | ✅ 已有，按语义分段 |
| **推拉运镜** | `zoompan` 滤镜（push_in/pull_out/pan_right/pan_left/tilt_up/tilt_down） | ✅ 已有，per-segment motion 属性 |
| **转场效果** | ffmpeg xfade（dissolve/slideleft/slideright/fadeblack/fadewhite 等） | ✅ 已有 |
| **Zoom Punch** | 边界帧 1.5× 放大裁剪（upper-centre 面部/发区） | ✅ 已有 |
| **画中画** | `_gen_detail_pip_frames` — 圆形遮罩+白边，叠加细节帧 | ✅ 已有（但仅 detail 类别） |
| **关键词高亮** | ASS 字幕金色高亮产品词/场景词/动作词 | ✅ 已有 |
| **动漫转场** | ComfyUI anime img2img 过渡帧 | ✅ 已有 |
| **背景移除** | GPU rembg (U2Net) 抠人像 | ✅ 已有 |
| **音乐卡点** | BGM 随机选取，无节拍对齐 | ⚠️ 弱 — 无节拍检测 |

### 2. 导演版（`director_video.py`）

| 能力 | 实现 | 效果 |
|------|------|------|
| **场景分镜脚本** | LLM 生成 scenes（含 scene_type: problem/comparison/detail 等） | ✅ 已有 |
| **镜头匹配** | DirectorMatcher 按 scene_type 匹配录像片段 | ✅ 已有 |
| **TTS 配音** | CosyVoice2 语音合成 | ✅ 已有 |
| **转场类型** | 8 种预设风格（dynamic/smooth/simple/trendy/emotional/lifestyle/luxury/contrast） | ✅ 已有 |
| **Zoom Punch** | phone_zoom 过渡（对比场景） | ✅ 已有 |
| **色彩分级** | 4 种预设（natural/vivid/warm/cool） | ✅ 已有 |
| **ASS 字幕** | 多行滚动字幕 | ✅ 已有 |

### 3. 自编版（creative pipeline）

| 能力 | 实现 | 效果 |
|------|------|------|
| **文案生成** | LLM 生成 vibe=creative 文案 | ✅ 已有 |
| **其余** | 复用导演版 pipeline | ✅ 继承 |

---

## 二、差距分析：用户反馈 vs 现有能力

| 抖音反馈需求 | 现有状态 | 差距 |
|-------------|---------|------|
| **增加特写展示网底和发丝细节** | Detail PiP 已有（圆形遮罩叠加） | ⚠️ 仅 detail 类别触发，覆盖面窄 |
| **分镜切换佩戴步骤** | 导演版有 wearing 类别匹配 | ⚠️ 但缺少 step-by-step 编号/标注 |
| **轻微推拉运镜** | zoompan 已有（push_in/pull_out） | ✅ 已有，但 motion 分配偏固定 |
| **画面更生动** | 转场+运镜+字幕 | ⚠️ 缺少：画中画标注、缩放聚焦、镜头分割粒度 |

### 核心问题

**直播录像是单镜头固定机位**，所以"镜头多变"完全依赖后期剪辑手段。现有 pipeline 已经做了大部分基础工作（分段、运镜、转场），但**缺少以下高级视觉增强**：

1. **动态画中画标注** — 类似"注意看这里👇"的箭头/圆圈标注，当前只有 detail 类别触发圆形 PiP
2. **镜头分割粒度不够细** — 按 SRT 段落切（通常 3-5s），但抖音偏好 1-2s 快切
3. **场景切换缺乏视觉区分** — 不同场景（佩戴前/佩戴后/细节展示）之间缺少明显的视觉过渡
4. **缺少"镜头语言"标注** — 如"正面→侧面→特写"的文字引导
5. **BGM 无节拍对齐** — 剪辑点没有跟着音乐节奏

---

## 三、可行方案评估

### 方案 A：增强现有经典版（推荐优先实施）

#### A1. 智能镜头分割细化
- **做法**：在 SRT 分段基础上，对长段落（>3s）用 ffmpeg 检测画面变化/运动峰值，进一步细分
- **GPU 成本**：低（ffmpeg 画面变化检测，CPU 即可）
- **实现难度**：⭐⭐
- **收益**：高 — 直接解决"镜头单一"问题

#### A2. 增强画中画标注
- **做法**：扩展 `_gen_detail_pip_frames` 的触发条件，不仅限于 detail 类别，增加：
  - **问题/对比场景**：左右分屏对比（佩戴前 vs 佩戴后）
  - **佩戴步骤**：编号标注（Step 1/2/3）+ 箭头指向
  - **特写关键词**：检测到"网底""发丝""仿真"时，叠加局部放大框
- **GPU 成本**：极低（Pillow 绘制，CPU）
- **实现难度**：⭐⭐
- **收益**：高 — 直接回应抖音反馈

#### A3. 运镜增强
- **做法**：改进 `motion` 属性的分配逻辑，当前按固定规则分配，改为：
  - 开场 → pull_out（全景引入）
  - 产品讲解 → push_in_strong（聚焦产品）
  - 步骤演示 → pan_right/pan_left（跟随动作）
  - 对比场景 → zoom_punch（强烈缩放）
  - 结尾 → pull_out（全景收尾）
- **GPU 成本**：零（纯 ffmpeg 参数调整）
- **实现难度**：⭐
- **收益**：中

### 方案 B：导演版视觉增强

#### B1. 场景视觉区分
- **做法**：在 `video_configs` 中增加更多视觉风格，针对不同 scene_type：
  - problem → 冷色调 + 快速 cut
  - comparison → 分屏效果（左右对比）
  - detail → 暖色调 + zoompan + PiP 标注
  - wearing → 中性色调 + 步骤编号
  - result → 高饱和 + dissolve 慢转场
- **GPU 成本**：中（分屏需要 ffmpeg 复杂滤镜链）
- **实现难度**：⭐⭐⭐
- **收益**：高

#### B2. 镜头分割指令注入
- **做法**：在 LLM 生成的 script 中增加 `camera_direction` 字段，如：
  ```json
  {
    "scene_id": 1,
    "text": "这款假发网底非常仿真",
    "camera_direction": "push_in_closeup",
    "transition_in": "zoomin",
    "transition_out": "dissolve"
  }
  ```
- **GPU 成本**：极低（仅 LLM prompt 调整）
- **实现难度**：⭐⭐
- **收益**：高

### 方案 C：高级效果（中期规划）

#### C1. BGM 节拍对齐
- **做法**：用 librosa 检测 BGM 节拍 → 剪辑点对齐节拍
- **GPU 成本**：低（CPU）
- **实现难度**：⭐⭐⭐⭐
- **收益**：中

#### C2. 关键帧高光提取
- **做法**：从直播录像中提取高光时刻（音量峰值 + 画面变化），作为额外素材
- **GPU 成本**：低
- **实现难度**：⭐⭐⭐
- **收益**：中

#### C3. 动态文字标注
- **做法**：在视频上叠加动态文字（"正面展示""侧面细节""佩戴步骤"），随镜头切换出现
- **GPU 成本**：中（ASS 字幕 + 淡入淡出）
- **实现难度**：⭐⭐
- **收益**：高

---

## 四、推荐实施计划

### Phase 1：立即可做（本周）

| 项目 | 文件 | 工作量 |
|------|------|--------|
| 增强画中画触发条件 | `editor.py` `_gen_detail_pip_frames` | 0.5 天 |
| 运镜分配逻辑优化 | `editor.py` `_build_zoompan_filter` | 0.5 天 |
| 导演版 camera_direction 字段 | `director_script.py` + `director_video.py` | 1 天 |
| 场景视觉区分增强 | `director_video.py` video_configs | 0.5 天 |

### Phase 2：短期（下周）

| 项目 | 文件 | 工作量 |
|------|------|--------|
| 智能镜头分割细化 | `transcribe.py` segment scorer | 1 天 |
| 动态文字标注 | `director_video.py` ASS 生成 | 0.5 天 |
| 对比场景分屏效果 | `director_video.py` GPU compose | 1 天 |

### Phase 3：中期（下下周）

| 项目 | 文件 | 工作量 |
|------|------|--------|
| BGM 节拍对齐 | `editor.py` + `librosa` | 1.5 天 |
| 关键帧高光提取 | `transcribe.py` | 1 天 |

---

## 五、技术可行性总结

| 抖音反馈需求 | 方案 | 可行性 | 优先级 |
|-------------|------|--------|--------|
| 增加特写展示网底和发丝细节 | A2 增强 PiP 触发 + A3 zoompan | ✅ 高 | P0 |
| 分镜切换佩戴步骤 | B1 场景视觉区分 + C3 动态标注 | ✅ 高 | P0 |
| 轻微推拉运镜 | A3 运镜分配优化 | ✅ 高 | P0 |
| 画面更生动 | A1 细粒度分割 + B2 camera_direction | ✅ 高 | P1 |
| 镜头多变感 | A1 + B1 组合 | ✅ 高 | P1 |

**结论**：现有技术栈已覆盖 80% 的需求，只需在现有能力上做增强，不需要引入新的 AI 模型或大幅架构变更。
