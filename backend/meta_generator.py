"""
LLM-based publish metadata generator.
Generates title / description / tags for a clip_group using Bedrock.
"""
import asyncio
import json
import logging
import os
import re
from typing import Optional

import aiosqlite
import httpx

from db import DB_PATH, aio_connect

logger = logging.getLogger(__name__)

BEDROCK_URL = "https://bedrock-runtime.us-east-1.amazonaws.com"
BEDROCK_MODEL = os.environ.get("BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-6")
BEDROCK_TOKEN = os.environ.get("AWS_BEARER_TOKEN_BEDROCK", "")
RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), "..", "recordings")

_META_PROMPT = """你是一位专注于「精致女性生活方式」赛道的抖音内容运营，负责为假发短视频撰写多套发布文案方案。

【核心要求】每次生成的文案必须有明显差异化：标题切入角度不同、情绪基调不同、描述的具体卖点不同。禁止出现相似的开头句式或相同的核心词组。把自己当作每次都在为不同视频写全新文案。

目标受众：16-40岁女性，追求精致日常、注重颜值管理，有一定消费力，对美发造型感兴趣。

产品信息：
- 假发款式：{wig_model}
- 颜色：{wig_color}
- 内容标签：{labels}
- 字幕摘要（直播片段）：{srt_excerpt}

请分析视频内容，生成以下4种方案（每种方案独立完整）。以JSON格式返回（只返回JSON，不含任何其他内容）：

{{
  "schemes": [
    {{
      "type": "种草",
      "title": "...",
      "description": "...",
      "tags": ["#标签1", "#标签2", "..."]
    }},
    {{
      "type": "催单",
      "title": "...",
      "description": "...",
      "tags": ["#标签1", "#标签2", "..."]
    }},
    {{
      "type": "产品介绍",
      "title": "...",
      "description": "...",
      "tags": ["#标签1", "#标签2", "..."]
    }},
    {{
      "type": "教学",
      "title": "...",
      "description": "...",
      "tags": ["#标签1", "#标签2", "..."]
    }}
  ]
}}

【通用禁止】节日/节气词（过年/春节/元旦等）；「姐妹」描述中出现 ≤ 1次（标题可出现1次）；禁止「绝绝子/yyds/爱了爱了/好家伙/破防了/buff叠满/OOTD/泰裤辣」等过时/低质网络词；禁止时效性标签；禁止「变美/显年轻X岁/遮住所有缺陷/彻底解决/保证效果」等效果承诺表述（巨量千川低质管控）；禁止「限时/最后X件/仅剩X单/抢完就没了/马上下架」等虚假紧迫感（平台直接降流）；标题字数严格 15~20 字，禁止标点堆叠和无意义符号（❗❗❗/‼️‼️/……等）；多用疑问句/场景句/对比句式提升点击率。
【标签要求】每种方案 5~8 个#标签（不超过10个），类型覆盖：品类词(1个，如#假发) + 款式颜色(1-2个) + 场景人群(1-2个) + 情绪种草(1-2个)；只使用假发/美发品类垂直标签，禁止蹭与假发无关的热门话题（平台识别为诱骗流量会降权）。

─────────────────────────────────
【方案1 · 种草】内容基调：自信、精致、有场景感；像闺蜜分享真实美好瞬间。
标题（≤25字）：每次必须从下列角度中选一个不同的切入，禁止重复：
  ▸ 他人目光/被夸：社交认可带来的愉悦（如「同事以为我新烫了发」）
  ▸ 专属场合：婚礼/面试/旅行/毕业季等具体场景
  ▸ 自我觉醒：找到了适合自己的那种造型
  ▸ 细节打动：某个工艺/颜色/质感让人心动的点
  ▸ 情绪共鸣：累了/烦了/想要改变时的治愈感
  ▸ 惊喜发现：没想到这款这么适合XXX脸型/发量
注意：禁止「反差/前后对比/佩戴前后」切入角度（巨量千川禁止暗示外貌改变）；禁止开头直接使用「出门五分钟/约会/通勤」等高频套话；多用疑问句（「这款发型凭什么这么火？」）或场景句（「上班路上被问了三次发型」）。
描述（120-180字）：
  1. 场景代入（1-2句）：第一/第二人称，制造具体画面感，切入角度与标题一致
  2. 种草展示（3-4句）：结合字幕提炼1-2个核心亮点，口语化有画面感，用自己的话说
  3. 互动收尾（1句）：开放式提问，每次换不同的问法

─────────────────────────────────
【方案2 · 催单】内容基调：价值感为主，紧迫感为辅，驱动粉丝从视频跳转下单。
标题（≤25字）：每次从下列触发角度中选一个，禁止每次都写「错过直播」：
  ▸ 产品价值锚点：为什么这款值得入手（工艺/颜色/性价比）
  ▸ 热销/问款：直播间反复被问、粉丝最多人选的款
  ▸ 换季/新造型：这个季节最适合的发型改变
  ▸ 送礼/自用两相宜：对自己好一点的理由
  ▸ 直播同价入口：强调小黄车方便，但不以「错过」为主诉求
描述（100-150字）：
  1. 自然引入（1句）：根据所选触发角度自然展开，不用固定公式
  2. 产品核心亮点（2-3句）：简洁说出1-2个最强卖点，每次侧重不同亮点
  3. 行动引导（1-2句）：「直播间同价，宝子们点左下方小黄车就可以下单」「喜欢直接冲，小黄车里有」；绝对禁止「最后X单/限时/仅剩X件/抢完就没了/马上下架」等紧迫感操控措辞（平台直接降流）

─────────────────────────────────
【方案3 · 产品介绍】内容基调：专业、清晰、有说服力，帮助观众了解产品细节。
标题（≤25字）：突出产品核心特点或使用场景。
  示例：「这款Bob头到底有多仙」「{wig_color}发色上头合集」「详解这款假发的3个优点」
描述（120-180字）：
  1. 引出产品（1句）：自然介绍这款产品
  2. 详细介绍（4-5句）：结合字幕摘要，说明款式、颜色、材质、佩戴感、适合场景等，选最相关的讲；只写真实产品参数，禁止「让你变美/遮住缺陷/效果惊人」等承诺性表述
  3. 适合人群（1句）：「发量少/发质受损/想尝试新造型的宝子都适合」
  4. 互动（1句）：「有问题评论区告诉我」

─────────────────────────────────
【方案4 · 教学】内容基调：实用、亲切，让观众觉得「我也能做到」。
仅在字幕摘要中出现佩戴步骤/搭配技巧/护理方法等教学内容时使用；若无相关内容，仍需生成但可以基于通用假发使用技巧。
标题（≤25字）：「一招教你」「手把手」「学会这个」等教学感句式。
  示例：「手把手教你戴出自然感」「一招让假发更服帖」「这样搭才不显假」
描述（120-180字）：
  1. 引出痛点（1-2句）：「很多宝子反映假发戴起来不自然...」
  2. 教学步骤（3-4句）：结合字幕中的具体技巧展开，动作感强，口语化
  3. 效果展示（1句）：说出做完之后的效果
  4. 互动（1句）：「学会了吗？有问题评论区问我」"""


async def _call_bedrock(prompt: str, max_tokens: int = 600) -> Optional[dict]:
    if not BEDROCK_TOKEN:
        logger.error("AWS_BEARER_TOKEN_BEDROCK not set")
        return None
    payload = {
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": {"maxTokens": max_tokens, "temperature": 0.95},
    }
    url = f"{BEDROCK_URL}/model/{BEDROCK_MODEL}/converse"

    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {BEDROCK_TOKEN}",
                        "Content-Type": "application/json",
                    },
                )
            if resp.status_code == 200:
                raw = resp.json()["output"]["message"]["content"][0]["text"]
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                if m:
                    return json.loads(m.group())
                logger.error(f"No JSON in Bedrock response: {raw[:200]}")
                return None
            elif resp.status_code in (429, 500, 502, 503) and attempt < 3:
                logger.warning(f"Bedrock {resp.status_code}, retrying (attempt {attempt}/3)...")
            else:
                logger.error(f"Bedrock error {resp.status_code}: {resp.text[:300]}")
                return None
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            if attempt < 3:
                logger.warning(f"Bedrock transient error ({e}), retrying (attempt {attempt}/3)...")
            else:
                logger.error(f"Bedrock call failed after 3 attempts: {e}")
                return None
        except Exception as e:
            logger.error(f"Bedrock call failed: {e}")
            return None

        await asyncio.sleep(2 ** attempt)  # 2s, 4s backoff

    return None


def _get_srt_excerpt(merged_filename: Optional[str], max_chars: int = 800) -> str:
    """Extract a short text sample from the group's merged SRT if available."""
    if not merged_filename:
        return ""
    srt_path = os.path.join(
        RECORDINGS_DIR,
        os.path.splitext(merged_filename)[0] + ".srt",
    )
    if not os.path.exists(srt_path):
        return ""
    try:
        with open(srt_path, encoding="utf-8") as f:
            content = f.read()
        lines = []
        for line in content.splitlines():
            line = line.strip()
            if not line or re.match(r"^\d+$", line) or re.match(r"^\d{2}:\d{2}:\d{2}", line):
                continue
            lines.append(line)
        text = " ".join(lines)
        return text[:max_chars]
    except Exception:
        return ""


def _generate_fallback_title(wig_model: str, wig_color: str, room_labels: str) -> dict:
    """生成简单的后备标题和描述"""
    import random
    
    # 基础模板
    templates = [
        f"😍 {wig_model}来了！{wig_color}超显白",
        f"✨ {wig_color}{wig_model}，气质绝了",
        f"💫 这个{wig_model}太好看了！{wig_color}显脸小", 
        f"🔥 {wig_color}{wig_model}，上头了",
        f"💄 {wig_model}姐妹冲！{wig_color}巨温柔"
    ]
    
    descriptions = [
        f"{wig_model}新款来啦！{wig_color}超级显白显气质，姐妹们快来试试~",
        f"最近超火的{wig_model}！{wig_color}真的太好看了，瞬间提升颜值！",
        f"{wig_color}{wig_model}绝了！温柔又显气质，姐妹们赶紧安排上！"
    ]
    
    tags = ["假发", "变美", "气质", "显脸小", "温柔", "种草"]
    if wig_model: tags.append(wig_model)
    if wig_color: tags.append(wig_color)
    
    return {
        "schemes": [{
            "type": "种草", 
            "title": random.choice(templates),
            "description": random.choice(descriptions),
            "tags": ",".join(random.sample(tags, min(6, len(tags))))
        }],
        "fallback": True
    }


async def generate_meta(group_id: int) -> Optional[dict]:
    """
    Generate publish metadata for a clip_group.
    Returns dict with keys: title, description, tags (comma-separated string).
    """
    async with aio_connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT g.wig_model, g.wig_color, g.merged_filename,
                      GROUP_CONCAT(DISTINCT r.session_label) as labels
               FROM clip_groups g
               LEFT JOIN recordings r ON r.group_id = g.id
               WHERE g.id = ?
               GROUP BY g.id""",
            (group_id,),
        ) as cur:
            group = await cur.fetchone()

    if not group:
        logger.error(f"Group {group_id} not found")
        return None

    srt_excerpt = _get_srt_excerpt(group["merged_filename"])
    prompt = _META_PROMPT.format(
        wig_model=group["wig_model"] or "未知款式",
        wig_color=group["wig_color"] or "未知颜色",
        labels=group["labels"] or "无",
        srt_excerpt=srt_excerpt or "无字幕",
    )

    result = await _call_bedrock(prompt, max_tokens=3000)
    if not result:
        # Bedrock失败时回退到本地备用文案库
        logger.warning(f"Bedrock generation failed for group {group_id}, using local fallback")
        try:
            from meta_library import get_random_schemes
            fallback_schemes = await get_random_schemes(4)  # 获取4个不同类型的方案
            if fallback_schemes:
                logger.info(f"Using {len(fallback_schemes)} fallback schemes from local library")
                return {"schemes": fallback_schemes, "fallback": True}
        except Exception as e:
            logger.error(f"Failed to get fallback schemes: {e}")
        return None

    # New multi-scheme format: {"schemes": [{type, title, description, tags}, ...]}
    schemes_raw = result.get("schemes", [])
    if schemes_raw:
        schemes = []
        for s in schemes_raw:
            tags = s.get("tags", [])
            tags_str = ",".join(tags) if isinstance(tags, list) else str(tags)
            schemes.append({
                "type": s.get("type", "种草"),
                "title": s.get("title", ""),
                "description": s.get("description", ""),
                "tags": tags_str,
            })
        return {"schemes": schemes}

    # Fallback: legacy single-scheme response
    tags = result.get("tags", [])
    tags_str = ",".join(tags) if isinstance(tags, list) else str(tags)
    return {
        "schemes": [{
            "type": "种草",
            "title": result.get("title", ""),
            "description": result.get("description", ""),
            "tags": tags_str,
        }]
    }


# ── Product keyword matching ──────────────────────────────────────────────────

async def match_product(group_id: int) -> Optional[dict]:
    """
    Match a product from the products table for a clip_group.
    Returns the best-matching product dict, or None.
    """
    async with aio_connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT wig_model, wig_color FROM clip_groups WHERE id = ?", (group_id,)
        ) as cur:
            group = await cur.fetchone()
        if not group:
            return None

        async with db.execute(
            "SELECT * FROM products WHERE enabled = 1"
        ) as cur:
            products = await cur.fetchall()

    keywords = [k for k in [group["wig_model"], group["wig_color"]] if k]
    if not keywords:
        return None

    # Score each product: exact match > substring match
    best_score = 0
    best_product = None
    for p in products:
        product_keywords = [kw.strip() for kw in (p["keywords"] or "").split(",") if kw.strip()]
        score = 0
        for kw in keywords:
            if kw in product_keywords:
                score += 2  # exact
            elif any(kw in pk or pk in kw for pk in product_keywords):
                score += 1  # substring
        if score > best_score:
            best_score = score
            best_product = dict(p)

    return best_product
