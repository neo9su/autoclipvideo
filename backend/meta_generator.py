"""
LLM-based publish metadata generator.
Generates title / description / tags for a clip_group using Bedrock.
"""
import asyncio
import json
import logging
import os
import random
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

# 8个文案维度池，每次随机抽4个，避免每次都生成相同的4种方案
_SCHEME_POOL = [
    {
        "type": "社交认可",
        "desc": "切入角度：被他人夸赞/问发型的真实场景，制造社交认可带来的愉悦感。情绪基调：自信、被认可、有点得意。",
        "title_hint": "如「上班路上被问了三次发型」「同事以为我新烫了发」",
        "desc_hint": "第一人称「我」开头，从具体社交场景切入（「我戴了3天，早上扎马尾都没掉，被同事问了两次」），引出产品，结合字幕中的具体参数/工艺，1句互动提问。需有1个真实使用细节（时间/动作/频次）。120-180字。",
    },
    {
        "type": "自我改变",
        "desc": "切入角度：想要改变、找到了适合自己的造型的自我觉醒感。情绪基调：治愈、释然、焕然一新。",
        "title_hint": "如「发量少又怕显头大？这款蓬松卷正好」「头大姐妹别再踩坑了，这款窄边真的救场」",
        "desc_hint": "标题先抛痛点，第一人称叙事，说明痛点（「我头围58cm，一直找不到合适的...」），引出这款如何解决，结合字幕中的具体工艺/参数，有连着用的时间跨度描述（「连着戴了一周」）。120-180字。",
    },
    {
        "type": "场合穿搭",
        "desc": "切入角度：某个具体场合（约会/面试/婚礼/旅行/毕业季/聚餐），这款假发帮你搞定造型。情绪基调：实用、精准、场景感强。",
        "title_hint": "如「约会时风吹发丝不僵硬，就靠这款」「面试当天换了这款，整个人精神多了」",
        "desc_hint": "标题先点痛点或场景需求，用场景代入，说明为什么这个场合选这款（结合字幕中的稳固性/舒适性/外观参数），末尾1句适合人群+互动。120-180字。",
    },
    {
        "type": "细节种草",
        "desc": "切入角度：某个工艺/颜色渐变/发丝质感让人心动的细节。情绪基调：精致、有眼光、发现美好。",
        "title_hint": "如「这个发色渐变处理真的太细腻了」「仔细看这个发丝，假发能做到这种程度」",
        "desc_hint": "从最打动人的一个可感知细节展开（必须是具体的：颜色渐变的层次/发丝的粗细/蕾丝边的宽度/克重数值），结合字幕中的工艺参数，再延伸到整体效果，末尾1句互动。120-180字。",
    },
    {
        "type": "产品介绍",
        "desc": "切入角度：专业、清晰地介绍这款假发的核心参数和使用场景，帮粉丝做决策。情绪基调：专业、有说服力。",
        "title_hint": "如「这款Bob头到底有什么不同」「详解这款假发的3个参数」",
        "desc_hint": "必须结合字幕中的具体参数（克重/材质/工艺），如字幕无参数则描述款式外观的具体细节。介绍款式/颜色/材质/佩戴感/适合场景，只写真实信息，禁止效果承诺，末尾1句适合人群（头围/发量/场景）+互动。120-180字。",
    },
    {
        "type": "使用教学",
        "desc": "切入角度：手把手教佩戴/搭配/护理技巧，让人觉得「我也能做到」。情绪基调：亲切、实用、有用。",
        "title_hint": "如「手把手教你戴出自然感」「一招让假发更服帖」",
        "desc_hint": "引出痛点（「每天早上五分钟」「扭头的时候发现没位移」），结合字幕中的技巧步骤，动作感强、口语化，末尾说效果+互动提问。120-180字。",
    },
    {
        "type": "价值催单",
        "desc": "切入角度：从产品价值/工艺/性价比切入，自然引导粉丝点小黄车下单。情绪基调：理性种草，行动引导。",
        "title_hint": "如「这个工艺这个价格，真的很值」「直播间被问最多的款来了」",
        "desc_hint": "1句自然引入价值（结合字幕中的具体工艺/参数），2-3句核心卖点，1-2句引导小黄车，绝对禁止「最后X单/限时/仅剩」等虚假紧迫感。100-150字。",
    },
    {
        "type": "疑问引发",
        "desc": "切入角度：用疑问句/反问句吊起好奇心，让人忍不住点进来看答案。情绪基调：好奇、探索、有悬念。",
        "title_hint": "如「头大姐妹怕假发显笨重？这款窄边设计真的不一样」「为什么买假发要选这个克重？」",
        "desc_hint": "标题抛出问题（痛点相关），描述给出答案（结合字幕中的具体参数/工艺），末尾再抛一个互动问题。120-180字。",
    },
    {
        "type": "痛点解决",
        "desc": "切入角度：直接点出一个具体痛点（头大/发量少/显笨重/夏天闷/容易滑），给出这款的针对性解法。情绪基调：共情、专业、有说服力。",
        "title_hint": "如「头大姐妹别再踩坑了，这款窄边设计真的救场」「发量少又怕显头大？这款蓬松卷正好」",
        "desc_hint": "1句痛点共情（「我知道头大的姐妹最怕...」），2-3句解决方案（必须结合字幕中的具体工艺/设计/参数），1句适合人群+互动。120-180字。",
    },
    {
        "type": "新潮种草",
        "desc": "切入角度：突出商品的「新潮属性」——新款/新色/趋势色/风格名称（Y2K/法式/奶油感等），让人感受到这款有鲜明的流行调性。情绪基调：有眼光、走在前面、分享发现感。",
        "title_hint": "如「今年最火的奶油感发色，这款全有了」「法式复古卷，这个颜色2026最流行」「联名款来了，限量的那种」",
        "desc_hint": "1句风格/趋势定位（「这是今年最流行的XXX风格」），2-3句产品具体描述（颜色/款式/质感），1句场景（「适合拍照/出片/穿搭搭配」），1句互动。120-180字。禁止编造「限量」「联名」信息，只在SRT有明确信号时使用；无趋势信号时从字幕里找风格词（日系/法式/复古）代替。",
    },
]

_META_PROMPT_TEMPLATE = """你是一位专注于「精致女性生活方式」赛道的抖音内容运营，负责为假发短视频撰写多套发布文案方案。

【核心要求】本次4套方案的切入角度必须完全不同，禁止复用相同的开头句式、情绪词或核心词组。每套方案独立完整，像为4个不同视频写的文案。

目标受众：16-40岁女性，追求精致日常、注重颜值管理，有一定消费力，对美发造型感兴趣。

产品信息：
- 假发款式：{wig_model}
- 颜色：{wig_color}
- 内容标签：{labels}
- 字幕摘要（直播片段）：{srt_excerpt}

本次请按以下4个方案维度各写一套（每套方案独立完整）。以JSON格式返回（只返回JSON，不含任何其他内容）：

{{"schemes": [
{scheme_placeholders}
]}}

─────────────────────────────────
{scheme_sections}
─────────────────────────────────

【通用禁止规则】
- 禁止节日/节气词（过年/春节/元旦等）
- 「姐妹」描述中出现 ≤ 1次（标题可出现1次）
- 禁止「绝绝子/yyds/爱了爱了/好家伙/破防了/buff叠满/OOTD/泰裤辣」等过时/低质网络词
- 禁止「变美/显年轻X岁/遮住所有缺陷/彻底解决/保证效果」等效果承诺（巨量千川低质管控）
- 禁止「限时/最后X件/仅剩X单/抢完就没了/马上下架」等虚假紧迫感（平台直接降流）
- 标题字数严格 15~20 字，禁止标点堆叠，Emoji 最多1个禁止堆叠
- 禁止「绝了/太绝了/真的绝/nb了」等空洞形容词
- 禁止「氛围感/说话算数/颜值天花板/仙气十足/绝美/超仙/高级感/高颜值」等无具体信息的空洞形容词
- 多用疑问句/场景句/对比句式提升点击率，合理使用具体数字（「3个方法/5秒搮定」）
- 禁止「已销售XX单/热销X件/明星同款/KOL同款/万人好评/全网最火」等无法核实的数据和背书
- 禁止「反差/前后对比/佩戴前后」角度（巨量千川禁止暗示外貌改变）
- 禁止无根据地声称「限量」「联名」「品牌新品」——只有字幕中有明确表述才能使用
- 趋势词使用规范：风格名称（Y2K/法式/奶油感/多巴胺）可以自由使用描述颜色调性；限量/联名/数量数据必须来自字幕

【真实具体要求】
- 每条描述至少包含1个具体参数（重量/材质/头围尺寸/工艺名称/具体克数/具体尺寸），如字幕中无参数则描述款式外观的具体细节（颜色渐变层次/发丝粗细/蕾丝边宽度）
- 描述内容必须来源于字幕中的实际信息，不得编造参数
- 用对比数字或具体场景代替抽象形容（「通勤戴2小时无位移」而非「很稳固」；「真人发丝，200g轻量化设计」而非「轻薄舒适」）

【痛点-解决结构要求】
- 每套文案在标题或描述开头必须隐含或明确一个用户痛点（头大/发量少/假发显假/夏天闷热/容易移位等）
- 禁止「单纯夸赞好看」的文案结构，必须有功能性或场景性支撑

【真诚语气要求】
- 优先使用第一人称「我」视角，避免广告腔「宝子们」开头
- 加入具体时间/次数/动作细节增加真实感（「戴了3天」「早上扎马尾没掉」「被问了两次」）
- 禁止连续3句以上都以感叹号结尾
- 描述中要有一个真实限制或注意事项（「头围偏大的话注意选大号」「刚戴的时候需要调整一下」），避免全程吹捧

【标签要求】每方案 5~8 个#标签，覆盖：品类词(1个，如#假发)+款式颜色(1-2个)+场景人群(1-2个)+情绪种草(1-2个)；只用假发/美发垂直标签，禁止蹭无关热门话题。

【信息深度要求】
- 基础信息：每套文案必须覆盖「是什么款式/颜色」「解决什么问题/适合谁」「怎么用/怎么戴」三个基础信息点
- 增值信息：在字幕有相关内容时，必须提炼以下增值信息之一：
  ① 对比信息（这款比同类轻多少/多了什么工艺）
  ② 使用细节（具体的佩戴动作/调整方式）
  ③ 场景延伸（除了日常还能用在哪些特殊场合）
- 禁止「大家都说好」式的泛化描述，用「我自己用了3天的感受是」「这款的发缝是这样处理的」等具体化表达

【价值观导向】
- 文案传递「精致生活是自己选择的」而非「变美才能被人看见」——强调自我愉悦，不强调他人评价
- 禁止暗示「不买这款就会变差/被比下去」的焦虑营销逻辑
- 正向表达：「这款帮我在赶时间的早晨多了5分钟喝咖啡的时间」而非「再也不用担心发型出丑了」
- 平等视角：用「我」说话，不用「姐妹你一定要...」的说教语气
【抖音广告违禁词专项禁止（六大类）】
① 绝对化夸大：禁止「最好/最佳/最优/最大/最高/最低/最便宜/最先进/最真实/最自然/最火」等含"最"词汇；禁止「第一/唯一/全网首发/独家/独一无二/NO.1/TOP.1」；禁止「顶级/极致/万能/史无前例/国家级/世界级/100%有效」
② 权威背书：禁止以国旗/国徽/领导人名义背书；禁止「国家机关专供/特供」；禁止无依据的「驰名商标/老字号/质量免检」
③ 虚假承诺：禁止「包过/永久有效/零风险/一洗白/稳赚不赔」；禁止「点击有惊喜/不点赞就划走/关注才能看结局」等诱导互动；禁止「5000万人已测」等虚构数据
④ 敏感内容：禁止政治/历史敏感内容；禁止「招财进宝/旺夫/旺宅/辟邪/逢凶化吉」等迷信词；禁止任何形式的性别/地域/种族歧视
⑤ 违规引流：禁止提及微信号/QQ/手机号/二维码/其他平台链接；禁止YYDS/OMG等拼音缩写规避审核
⑥ 医疗限制：禁止「防脱发（医疗用途）/治愈脱发/修复发囊」等医疗声称；禁止医生形象背书

替代方案参考：「最好」→「很好用」；「顶级」→「优质」；「100%」→「基本上」；「永久」→「长期」；「防脱发」→「呵护发丝」；「旺夫/辟邪」→直接删除
"""


def _build_meta_prompt(
    wig_model: str,
    wig_color: str,
    labels: str,
    srt_excerpt: str,
    num_schemes: int = 4,
) -> tuple[str, list[str]]:
    """
    Randomly sample num_schemes from _SCHEME_POOL and build the generation prompt.
    Returns (prompt_text, [type_names_in_order]).
    """
    sampled = random.sample(_SCHEME_POOL, min(num_schemes, len(_SCHEME_POOL)))

    # Build per-scheme section instructions
    sections = []
    for i, s in enumerate(sampled, 1):
        sections.append(
            f"【方案{i} \u00b7 {s['type']}\u3011{s['desc']}\n"
            f"标题提示：{s['title_hint']}\n"
            f"描述要求：{s['desc_hint']}"
        )

    # Build JSON placeholder lines
    placeholders = []
    for s in sampled:
        placeholders.append(
            f'  {{"type": "{s["type"]}", "title": "...", "description": "...", "tags": ["#\u6807\u7b7e1", "..."]}}'
        )

    prompt = _META_PROMPT_TEMPLATE.format(
        wig_model=wig_model,
        wig_color=wig_color,
        labels=labels,
        srt_excerpt=srt_excerpt,
        scheme_placeholders=",\n".join(placeholders),
        scheme_sections="\n\n".join(sections),
    )
    return prompt, [s["type"] for s in sampled]


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
            async with httpx.AsyncClient(timeout=120.0) as client:
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


def _read_srt_text(srt_path: str, max_chars: int) -> str:
    try:
        with open(srt_path, encoding="utf-8") as f:
            content = f.read()
        lines = []
        for line in content.splitlines():
            line = line.strip()
            if not line or re.match(r"^\d+$", line) or re.match(r"^\d{2}:\d{2}:\d{2}", line):
                continue
            lines.append(line)
        return " ".join(lines)[:max_chars]
    except Exception:
        return ""


def _get_srt_excerpt(merged_filename: Optional[str], max_chars: int = 800) -> str:
    """Extract a short text sample from the group's merged SRT if available."""
    if merged_filename:
        srt_path = os.path.join(
            RECORDINGS_DIR,
            os.path.splitext(merged_filename)[0] + ".srt",
        )
        if os.path.exists(srt_path):
            text = _read_srt_text(srt_path, max_chars)
            if text:
                return text
    return ""


async def _get_srt_excerpt_with_fallback(group_id: int, merged_filename: Optional[str], max_chars: int = 800) -> str:
    """Try merged SRT first, then fall back to first available per-recording SRT."""
    text = _get_srt_excerpt(merged_filename, max_chars)
    if text:
        return text

    async with aio_connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT filename FROM recordings
               WHERE group_id = ? AND clipped = 2
               ORDER BY start_time ASC""",
            (group_id,),
        ) as cur:
            rows = await cur.fetchall()

    for row in rows:
        srt_path = os.path.join(
            RECORDINGS_DIR,
            os.path.splitext(row["filename"])[0] + ".srt",
        )
        if os.path.exists(srt_path):
            text = _read_srt_text(srt_path, max_chars)
            if text:
                return text
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

    srt_excerpt = await _get_srt_excerpt_with_fallback(group_id, group["merged_filename"])
    prompt, scheme_types = _build_meta_prompt(
        wig_model=group["wig_model"] or "未知款式",
        wig_color=group["wig_color"] or "未知颜色",
        labels=group["labels"] or "无",
        srt_excerpt=srt_excerpt or "无字幕",
    )
    logger.info(f"[group {group_id}] Generating meta with schemes: {scheme_types}")

    result = await _call_bedrock(prompt, max_tokens=3000)
    if not result:
        # Bedrock失败时回退到本地备用文案
        logger.warning(f"Bedrock generation failed for group {group_id}, using local fallback")
        try:
            fallback = _generate_fallback_title(
                wig_model=group["wig_model"] or "假发",
                wig_color=group["wig_color"] or "自然色",
                room_labels=group["labels"] or "",
            )
            if fallback and fallback.get("schemes"):
                logger.info(f"[group {group_id}] Using fallback schemes")
                return fallback
        except Exception as e:
            logger.error(f"Failed to generate fallback: {e}")
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
