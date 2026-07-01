"""
导演模式脚本生成器
复用现有Bedrock配置，基于Claude生成短视频剧本
"""
import asyncio
import json
import logging
import os
import time
from typing import Dict, List, Optional
import httpx

from llm_client import llm_post, LLM_MODEL as BEDROCK_MODEL

logger = logging.getLogger(__name__)

# 兼容旧变量名（部分地方引用）
_LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
BEDROCK_URL = _LLM_BASE_URL


def _get_bedrock_token() -> str:
    return os.environ.get("LLM_API_KEY", "")

# ── Vibe 定义 ──────────────────────────────────────────────────────────────────
# 每种 vibe 决定脚本的叙事风格、情绪曲线、配音基调、背景音乐方向

VIBE_CONFIGS = {
    "trendy": {
        "label": "爆款型",
        "description": "快节奏、强钩子、追热点，黄金3秒抓眼球，节拍感强",
        "narrative": "悬念式开场 → 快速展示 → 强对比 → 爆梗收尾",
        "pacing": "fast",
        "scene_count_range": (4, 6),
        "music_style": "流行电子、动感BGM、节拍清晰",
        "default_scene_sequence": [
            "hook", "transformation", "demonstration", "social_proof", "promotion", "cta"
        ],
        "copywriting_style": "简洁有力、节奏感强、口语自然",
    },
    "emotional": {
        "label": "情感型",
        "description": "情感共鸣为主，讲故事，引发共情，让观众感同身受",
        "narrative": "共情痛点 → 情感铺垫 → 解决方案 → 感动收尾",
        "pacing": "slow",
        "scene_count_range": (4, 5),
        "music_style": "温柔钢琴、情感流行、轻音乐",
        "default_scene_sequence": [
            "hook", "problem", "solution", "transformation", "cta"
        ],
        "copywriting_style": "第一人称、感同身受、真实故事感、温柔语气",
    },
    "lifestyle": {
        "label": "生活型",
        "description": "GRWM风格，日常化、真实感、随手拍质感，接地气",
        "narrative": "日常场景切入 → 自然展示 → 生活化对白 → 轻松收尾",
        "pacing": "medium",
        "scene_count_range": (4, 5),
        "music_style": "清新indie、咖啡馆BGM、轻爵士",
        "default_scene_sequence": [
            "hook", "demonstration", "social_proof", "promotion", "cta"
        ],
        "copywriting_style": "口语化、自言自语式、朋友间对话感",
    },
    "luxury": {
        "label": "高端型",
        "description": "品质感、精致、仪式感，打造高档视觉调性",
        "narrative": "质感开场 → 细节特写 → 品质卖点 → 高端收尾",
        "pacing": "slow",
        "scene_count_range": (4, 5),
        "music_style": "古典轻音乐、优雅钢琴、轻奢BGM",
        "default_scene_sequence": [
            "hook", "demonstration", "solution", "transformation", "cta"
        ],
        "copywriting_style": "精准词汇、有画面感、优雅克制、强调品质细节",
    },
    "contrast": {
        "label": "反差型",
        "description": "意外感、强对比、出乎意料，用反差制造记忆点",
        "narrative": "反直觉钩子 → 挑战预期 → 真相大揭秘 → 惊喜收尾",
        "pacing": "fast",
        "scene_count_range": (4, 6),
        "music_style": "戏剧性配乐、反差音效、综艺BGM",
        "default_scene_sequence": [
            "hook", "problem", "transformation", "social_proof", "urgency", "cta"
        ],
        "copywriting_style": "对比鲜明、转折自然、重点突出",
    },
    "creative": {
        "label": "自编文案",
        "description": "完全创作型文案，不受直播内容约束，自由发挥产品卖点，节奏紧凑有力",
        "narrative": "吸引开场 → 产品亮点 → 使用效果 → 适合人群 → 催单收尾",
        "pacing": "fast",
        "scene_count_range": (6, 8),
        "music_style": "动感电子、节拍清晰",
        "default_scene_sequence": [
            "hook", "demonstration", "transformation", "social_proof", "urgency", "cta"
        ],
        "copywriting_style": "每句20~30字、句子饱满完整、自然口语、不叠词、每句话独立完整",
    },
    "kuku": {
        "label": "KUKU人设",
        "description": "专业假发博主视角，有态度、有品味，像朋友推荐而非推销员，擅长发现细节美",
        "narrative": "细节发现 → 专业解读 → 真实体感 → 场景代入 → 自然收尾",
        "pacing": "medium",
        "scene_count_range": (4, 5),
        "music_style": "轻电子、节奏感适中、不喧宾夺主",
        "default_scene_sequence": ["hook", "detail", "demonstration", "scene", "cta"],
        "copywriting_style": "第一人称、有见解、具体细节、口语自然不做作",
    },
}

# 场景类型说明（供 Claude 参考）
SCENE_TYPE_GUIDE = """
可用场景类型（从中选择最适合当前 vibe 的4-6个）：
- hook:          黄金开场钩子，3-5秒内吸引停留，可以是反问、悬念、强视觉
- problem:       痛点场景，展示目标用户的困扰（脱发、发量稀少、发型单调等）
- solution:      产品作为解决方案的出场，自然、流畅
- demonstration: 产品使用演示，展示效果、质感、佩戴体验
- social_proof:  社会认同，用真实佩戴体验/口感描述体现认可感，禁止写销量数据/达人背书/博主推荐等无授权声称
- transformation:蜕变对比，before→after，视觉冲击力最强
- promotion:     活动/价格/折扣，要有紧迫感但不生硬
- urgency:       引导行动，用「直播间小黄车/点关注」代替库存/限时等虚假紧迫感
- cta:           行动召唤，引导点赞/关注/下单，要具体
"""


class DirectorScriptGenerator:
    def __init__(self):
        if not _get_bedrock_token():
            logger.error("AWS_BEARER_TOKEN_BEDROCK not set")

    async def generate_script(
        self,
        srt_content: str,
        wig_model: str,
        wig_color: str,
        room_name: str = "",
        script_type: str = "balanced",
        vibe: str = "trendy",
    ) -> Dict:
        """
        生成导演脚本

        Args:
            srt_content:  SRT字幕内容
            wig_model:    假发款式
            wig_color:    假发颜色
            room_name:    直播间名称
            script_type:  脚本类型（保留兼容性，vibe 优先）
            vibe:         创意基调 trendy/emotional/lifestyle/luxury/contrast

        Returns:
            Dict: 结构化脚本JSON
        """
        prompt = self._build_script_prompt(
            srt_content, wig_model, wig_color, room_name, script_type, vibe
        )

        script_text = await llm_post(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=3000,
            temperature=0.9,
            timeout=60.0,
        )
        if script_text is None:
            logger.error("Script generation: LLM returned None")
            return self._fallback_script(vibe)
        return self._parse_script_response(script_text, vibe)

    def _build_script_prompt(
        self,
        srt_content: str,
        wig_model: str,
        wig_color: str,
        room_name: str,
        script_type: str,
        vibe: str,
    ) -> str:
        """构建高想象力脚本生成提示词"""

        vc = VIBE_CONFIGS.get(vibe, VIBE_CONFIGS["trendy"])
        min_scenes, max_scenes = vc["scene_count_range"]

        # creative vibe 使用独立 prompt
        if vibe == "creative":
            return self._build_creative_prompt(wig_model, wig_color, min_scenes, max_scenes, script_type)

        # kuku vibe 使用独立 prompt
        if vibe == "kuku":
            return self._build_kuku_prompt(srt_content, wig_model, wig_color, min_scenes, max_scenes, script_type)

        # 提取 SRT 纯文字（去掉时间码行，保留内容）
        import re
        text_lines = [
            ln.strip()
            for ln in srt_content.splitlines()
            if ln.strip() and not re.match(r"^\d+$", ln.strip()) and "-->" not in ln
        ]
        srt_summary = " ".join(text_lines)[:2500]

        return f"""你是假发短视频文案编辑，任务是把直播录音提炼成一条45-60秒的产品介绍视频配音脚本。

【直播原始转录】
{srt_summary}

【产品信息】
款式：{wig_model or "假发"}  颜色：{wig_color or "自然色"}  平台：抖音  时长：45-60秒

【核心要求】
1. 文案必须100%来源于直播内容——主播说了什么，你就提炼什么，不要编造、不要夸大
2. 重点讲产品细节和使用方法——发丝材质、网底工艺、佩戴步骤、打理技巧、适合头型脸型、固定方式等实用信息优先；少讲空话和情绪渲染
3. 禁止营销话术——不要「姐妹们」「真的绝了」「赶紧冲」「谁懂啊」「必入」等营销腔；用平实的产品介绍语气，像教程一样告诉观众这个产品怎么用、有什么特点
4. 叙事结构：根据直播内容选择最适合的叙事线，从以下3种中选一种：
   A) 产品讲解型：从产品核心特征切入 → 工艺/材质细节 → 佩戴演示步骤 → 适用场景 → 收尾
   B) 使用教学型：从佩戴/打理场景切入 → 具体操作步骤 → 效果展示 → 注意事项 → 收尾
   C) 对比展示型：从一个具体差异点切入 → 展示对比效果 → 解释工艺原因 → 适合人群 → 收尾
   根据直播SRT内容，选择最匹配的那条叙事线并在 narrative_structure 里注明选了哪条。
5. 每句话独立完整，能单独朗读出来让人听懂，不允许出现语义截断或上下文跳跃
6. 口语化但不用网络套话——禁止使用「等等等等」「你看你看」「注意注意」「哇哦」「OMG」「绝绝子」等无意义填充词
7. 不要有库存/断货/紧迫感等催单内容，除非直播录音里明确提到
8. 结尾统一用：「喜欢这款的姐妹记得点关注收藏，下次上新第一时间通知你！」
9. 开场第一句（hook）必须在 3 秒内吸引注意，用产品细节/使用场景/具体问题开场，禁止「大家好我是」「今天给大家介绍」等无聊开场
10. 禁止「限时/最后X件/仅剩X单/抢完就没了」等虚假紧迫感措辞（平台直接降流）
11. 禁止「绝绝子/yyds/爱了爱了/好家伙/破防了」等过时网络词
12. 禁止以下需要授权书或数据证据才能使用的表述："已销售XX单""卖出X万单""XX博主都在用""明星同款""达人推荐""粉丝强烈推荐""万人好评""全网最火""抖音TOP1""同类第一""官方认证"
13. 内容密度优先：每句话都必须带有具体信息（尺寸/材质/步骤/工艺名称），禁止「非常好看」「特别自然」「很舒服」等空洞形容词，必须替换为具体描述（如「仿真头皮PU材质」「发丝是耐热丝可以卷」「网底透气孔间距2mm」）
14. 使用方法必讲：如果直播里展示了佩戴步骤、调节方法、打理技巧，必须提炼进文案，这是观众最需要的实用内容
15. 趋势识别：如果直播SRT里出现「新款/上新/联名/限定/今年流行/Y2K/法式/奶油感」等词，
    必须在 key_messages 里提炼为卖点，并在对应场景的 voiceover_text 里自然带出
16. 信息完整性：每条视频必须覆盖至少以下3个维度：
    - 产品细节：材质/工艺/结构（网底类型、发丝种类、尺寸参数）
    - 使用方法：佩戴步骤/固定方式/调节技巧/日常打理
    - 效果展示：适合什么脸型头型/实际佩戴效果/前后对比
17. 增值内容优先：如直播里有对比（「这款比XXX多了一圈蕾丝边」「比普通假发轻了30g」），优先提炼为卖点；对比信息比单独介绍更有说服力

【节奏风格参考】{vc["label"]}：{vc["description"]}

请输出严格的JSON，不要有任何注释或前言，直接输出{{}}：

【camera_direction 填写指南】
- hook（开头）: pull_out（全景引入）
- problem: push_in（聚焦问题）
- comparison: push_in_strong（强烈聚焦对比）
- wearing: pan_right/pan_left（跟随动作）
- detail: push_in_strong（特写推进）
- product: push_in（产品聚焦）
- result/scene: pull_out（全景展示）
- social_proof: static（静态展示）
- conversion/cta: pull_out（收尾拉远）

【transition_type 填写指南】
- hook: zoomin（快速推进）
- comparison: dissolve（叠化对比）
- wearing: xfade（常规切换）
- detail: fadeblack（黑场过渡）
- result: fadewhite（白场过渡）
- cta: fadeblack（黑场收尾）

{{
    "vibe": "{vibe}",
    "vibe_label": "{vc["label"]}",
    "script_type": "{script_type}",
    "narrative_structure": "本视频的叙事结构概述",
    "total_duration": 55,
    "music_style": "{vc["music_style"]}",
    "pacing": "{vc["pacing"]}",
    "scenes": [
        {{
            "scene_id": 1,
            "timestamp_start": 0,
            "timestamp_end": 8,
            "scene_type": "hook",
            "description": "画面描述",
            "voiceover_text": "配音文案（完整一句话，来自直播内容提炼）",
            "emotion": "natural",
            "visual_requirements": ["镜头描述"],
            "camera_angle": "特写/中景/全景",
            "transition": "快切/淡入/叠化",
            "camera_direction": "push_in/pull_out/pan_right/pan_left/static",
            "transition_type": "xfade/fadeblack/fadewhite/dissolve/slideleft/slideright/zoomin"
        }}
    ],
    "emotional_arc": ["场景1情绪"],
    "key_messages": ["卖点1", "卖点2"],
    "viral_hook": "开头第一句话",
    "call_to_action": "结尾行动召唤",
    "style_notes": "执行备注"
}}

【抖音广告违禁词——配音文案必须遵守】
① 绝对化夸大：禁止「最好/最佳/最优/最高/最低/最便宜/最先进/最真实/最自然/最火」等含"最"词；禁止「第一/唯一/全网首发/独家/独一无二/NO.1/TOP.1」；禁止「顶级/极致/万能/史无前例/国家级/世界级/100%有效」
② 权威背书：禁止以国旗/国徽/领导人名义背书；禁止「国家机关专供/特供」；禁止无依据的「驰名商标/老字号/质量免检」
③ 虚假承诺：禁止「包过/永久有效/零风险/一洗白/稳赚不赔」；禁止「点击有惊喜/不点赞就划走/关注才能看结局」等诱导互动；禁止虚构数据如「5000万人已测」
④ 敏感内容：禁止政治/历史敏感；禁止「招财进宝/旺夫/旺宅/辟邪/逢凶化吉」等迷信词；禁止任何歧视性言论
⑤ 违规引流：禁止提及微信/QQ/手机号/二维码/其他平台链接；禁止YYDS/OMG等拼音缩写
⑥ 医疗限制：禁止「防脱发（医疗功效）/治愈脱发/修复发囊」等医疗声称；禁止医生形象背书

替代方案参考：「最好」→「很好用」；「顶级」→「优质」；「100%」→「基本上」；「永久」→「长期」；「防脱发」→「呵护发丝」；「旺夫/辟邪」→直接删除

场景数量：{min_scenes}~{max_scenes}个，emotion 从以下选择：
warm / clear / natural / persuasive / confident / storytelling"""

    def _build_creative_prompt(self, wig_model: str, wig_color: str,
                               min_scenes: int, max_scenes: int, script_type: str) -> str:
        """自编文案 prompt：完全创作型，不依赖直播内容，允许编造卖点和催单。"""
        return f"""你是抖音假发短视频文案编辑，为一款假发产品写一条50-60秒的配音脚本。

【产品信息】
款式：{wig_model or "时尚假发"}  颜色：{wig_color or "自然色"}

【写作要求】
1. 完全自由创作——根据产品款式和颜色，发挥想象力写出吸引人的卖点
2. 禁止编造销量、用户评价、博主背书等需要授权或数据证明的内容；可以描述产品外观/质感/佩戴体验等客观特点
3. 每句话20~30字，句子要完整、饱满，不要过短，朗读出来至少需要3秒；结合产品特点说完整，让听众一句话就能记住一个卖点
4. 严禁叠词开场——不能用「等等等等」「你看你看」「哇哦哇哦」「姐妹姐妹」等重复词，每个词只说一次；禁止「绝绝子/yyds/爱了爱了/好家伙/破防了」等过时网络词
5. 每个场景的配音是完整独立的一句话，朗读出来语义完整、不截断
6. 口语化，像朋友推荐，不像广告播音腔
7. 结尾固定用：「喜欢的姐妹，赶紧点小黄车，点关注不迷路！」
8. 开场第一句必须是强钉子：用提问（「你知道为什么这款这么火吗？」）、悬念（「很多人第一次看到这个颜色都怠住了」）或场景代入，禁止无聊开场
9. 禁止虚假紧迫感：不写「限时/最后X件/仅剩X单/抢完就没了」，催单用「直播间小黄车/点关注」代替

【时长硬性要求】
- 总配音时长必须达到 50-60 秒（约 180-240 字）
- 每个场景配音 20-30 字，朗读约 3-5 秒
- 场景数量必须 ≥ 6 个（确保总时长足够）
- 如果场景少于6个，说明文案太短，必须增加场景直到总字数≥180字
- 写完自检：把所有 voiceover_text 加起来，如果总字数<180字，必须重写加长

叙事结构：根据产品款式和颜色选择最适合的叙事线，从以下3种中选一种：
   A) 痛点驱动型：「你有没有遇到过...」痛点共情 → 「我找到了一个方法」解决方案 → 具体展示 → 场景代入 → 轻收尾
   B) 细节发现型：从最打动人的一个细节切入（颜色/质感/工艺）→ 延伸到整体 → 适合场景 → 互动收尾
   C) 社交验证型：从他人反应切入（同事问/朋友夸）→ 揭秘是什么 → 展示产品 → 同类人群 → 收尾
   在 narrative_structure 字段注明选了哪条叙事线。

请输出严格的JSON，直接输出{{}}不要前言不要解释不要markdown代码块标记：

{{
    "vibe": "creative",
    "vibe_label": "自编文案",
    "script_type": "{script_type}",
    "narrative_structure": "创意叙事结构概述",
    "total_duration": 55,
    "music_style": "动感电子、节拍清晰",
    "pacing": "fast",
    "scenes": [
        {{
            "scene_id": 1,
            "timestamp_start": 0,
            "timestamp_end": 8,
            "scene_type": "hook",
            "description": "画面描述",
            "voiceover_text": "配音文案（完整一句话，20-30字，语义完整）",
            "emotion": "confident",
            "visual_requirements": ["镜头描述"],
            "camera_angle": "特写/中景",
            "transition": "快切",
            "camera_direction": "push_in/pull_out/pan_right/pan_left/static",
            "transition_type": "xfade/fadeblack/fadewhite/dissolve/slideleft/slideright/zoomin"
        }}
    ],
    "emotional_arc": ["场景情绪"],
    "key_messages": ["卖点1", "卖点2"],
    "viral_hook": "开头第一句",
    "call_to_action": "结尾召唤",
    "style_notes": "执行备注"
}}

【抖音广告违禁词——配音文案必须遵守】
① 绝对化夸大：禁止「最好/最佳/最优/最高/最低/最便宜/最先进/最真实/最自然/最火」等含"最"词；禁止「第一/唯一/全网首发/独家/独一无二/NO.1/TOP.1」；禁止「顶级/极致/万能/史无前例/国家级/世界级/100%有效」
② 权威背书：禁止以国旗/国徽/领导人名义背书；禁止「国家机关专供/特供」；禁止无依据的「驰名商标/老字号/质量免检」
③ 虚假承诺：禁止「包过/永久有效/零风险/一洗白/稳赚不赔」；禁止「点击有惊喜/不点赞就划走/关注才能看结局」等诱导互动；禁止虚构数据如「5000万人已测」
④ 敏感内容：禁止政治/历史敏感；禁止「招财进宝/旺夫/旺宅/辟邪/逢凶化吉」等迷信词；禁止任何歧视性言论
⑤ 违规引流：禁止提及微信/QQ/手机号/二维码/其他平台链接；禁止YYDS/OMG等拼音缩写
⑥ 医疗限制：禁止「防脱发（医疗功效）/治愈脱发/修复发囊」等医疗声称；禁止医生形象背书

替代方案参考：「最好」→「很好用」；「顶级」→「优质」；「100%」→「基本上」；「永久」→「长期」；「防脱发」→「呵护发丝」；「旺夫/辟邪」→直接删除

场景数量：{min_scenes}~{max_scenes}个（最少6个），emotion 从以下选择：
warm / clear / natural / persuasive / confident / urgent

⚠️ 重要：输出必须是合法JSON，不要任何额外文字、注释或markdown标记。直接以{{开头。"""

    def _build_kuku_prompt(self, srt_content: str, wig_model: str, wig_color: str,
                           min_scenes: int, max_scenes: int, script_type: str) -> str:
        """KUKU直播间专属 prompt：专业假发博主视角，有态度有品味，像朋友推荐。"""
        import re
        text_lines = [
            ln.strip()
            for ln in srt_content.splitlines()
            if ln.strip() and not re.match(r"^\d+$", ln.strip()) and "-->" not in ln
        ]
        srt_summary = " ".join(text_lines)[:2500]

        return f"""你是KUKU假发直播间的内容编辑，任务是把直播录音提炼成一条45-60秒的产品介绍视频配音脚本。

【直播原始转录】
{srt_summary}

【产品信息】
款式：{wig_model or "假发"}  颜色：{wig_color or "自然色"}  平台：抖音  时长：45-60秒

【KUKU人设风格要求】
- 以「专业假发爱好者」视角说话，不是推销员，是真心喜欢这款才推荐
- 至少有1句带有个人观点的表述（「我觉得这个颜色比XXX更适合日常」「个人更喜欢这款的...」）
- 语气亲切但有自己的判断力，不是所有东西都夸，要有「这款特别适合XXX人」的针对性建议
- 避免过度催单语气，收尾用「感兴趣的可以了解一下」代替「赶紧抢」

【叙事结构】细节发现 → 专业解读 → 真实体感 → 场景代入 → 自然收尾
从最打动人的一个细节切入（颜色/质感/工艺）→ 结合直播内容做专业解读 → 描述真实佩戴感受 → 点出最适合的场景 → 自然收尾

【核心要求】
1. 文案必须100%来源于直播内容，不要编造、不要夸大
2. 每句话独立完整，能单独朗读出来让人听懂
3. 口语化，第一人称，像在跟朋友聊天
4. 细节代替形容词：「发丝递针工艺，贴近头皮3mm」比「非常真实自然」更有说服力
5. 场景具体化：「约会前5分钟」比「日常场合」更有画面感
6. 开场第一句必须在3秒内吸引注意，用细节发现/个人体验/好奇钩子开场
7. 禁止「限时/最后X件/仅剩X单/抢完就没了」等虚假紧迫感
8. 禁止「绝绝子/yyds/爱了爱了/破防了」等过时网络词
9. 禁止「已销售XX单/明星同款/万人好评/全网最火」等无授权声称
10. 信息覆盖：外观（颜色/款式）+ 功能（解决什么/适合谁）+ 体验（佩戴感受）三个维度都要有

请输出严格的JSON，直接输出{{}}不要前言不要解释不要markdown代码块标记：

{{
    "vibe": "kuku",
    "vibe_label": "KUKU人设",
    "script_type": "{script_type}",
    "narrative_structure": "细节发现型——从[具体细节]切入",
    "total_duration": 55,
    "music_style": "轻电子、节奏感适中、不喧宾夺主",
    "pacing": "medium",
    "scenes": [
        {{
            "scene_id": 1,
            "timestamp_start": 0,
            "timestamp_end": 8,
            "scene_type": "hook",
            "description": "画面描述",
            "voiceover_text": "配音文案（完整一句话，来自直播内容提炼）",
            "emotion": "natural",
            "visual_requirements": ["镜头描述"],
            "camera_angle": "特写/中景/全景",
            "transition": "快切/淡入/叠化",
            "camera_direction": "push_in/pull_out/pan_right/pan_left/static",
            "transition_type": "xfade/fadeblack/fadewhite/dissolve/slideleft/slideright/zoomin"
        }}
    ],
    "emotional_arc": ["场景1情绪"],
    "key_messages": ["卖点1", "卖点2"],
    "viral_hook": "开头第一句话",
    "call_to_action": "感兴趣的可以了解一下",
    "style_notes": "执行备注"
}}

【抖音广告违禁词——配音文案必须遵守】
① 绝对化夸大：禁止「最好/最佳/最优/最高/最低/最便宜/最先进/最真实/最自然/最火」等含"最"词；禁止「第一/唯一/全网首发/独家/独一无二/NO.1/TOP.1」；禁止「顶级/极致/万能/史无前例/国家级/世界级/100%有效」
② 权威背书：禁止以国旗/国徽/领导人名义背书；禁止「国家机关专供/特供」；禁止无依据的「驰名商标/老字号/质量免检」
③ 虚假承诺：禁止「包过/永久有效/零风险/一洗白/稳赚不赔」；禁止「点击有惊喜/不点赞就划走/关注才能看结局」等诱导互动；禁止虚构数据如「5000万人已测」
④ 敏感内容：禁止政治/历史敏感；禁止「招财进宝/旺夫/旺宅/辟邪/逢凶化吉」等迷信词；禁止任何歧视性言论
⑤ 违规引流：禁止提及微信/QQ/手机号/二维码/其他平台链接；禁止YYDS/OMG等拼音缩写
⑥ 医疗限制：禁止「防脱发（医疗功效）/治愈脱发/修复发囊」等医疗声称；禁止医生形象背书

替代方案参考：「最好」→「很好用」；「顶级」→「优质」；「100%」→「基本上」；「永久」→「长期」；「防脱发」→「呵护发丝」；「旺夫/辟邪」→直接删除

场景数量：{min_scenes}~{max_scenes}个，emotion 从以下选择：
warm / clear / natural / persuasive / confident / storytelling"""

    @staticmethod
    def _sanitize_voiceover(text: str) -> str:
        """替换配音文案中的抖音广告违禁词为安全同义词（兜底后处理层）。"""
        import re as _re
        replacements = [
            # ① 绝对化夸大 — 含"最"的词
            (r"最好用", "很好用"), (r"最好看", "很好看"), (r"最好", "挺好的"),
            (r"最佳", "较好的"), (r"最优", "优质的"), (r"最大", "尺寸大"),
            (r"最高", "相当高"), (r"最低", "相当低"), (r"最便宜", "价格实惠"),
            (r"最先进", "工艺成熟"), (r"最真实", "很真实"), (r"最自然", "很自然"),
            (r"最火", "很受欢迎"), (r"最受欢迎", "广受好评"), (r"最流行", "很流行"),
            # ① 含"一/首/独"的绝对化
            (r"第一款", "一款"), (r"第一名", "热门款"),
            (r"唯一", "少见的"), (r"全网首发", "新推出的"),
            (r"独家", "特有的"), (r"独一无二", "独特的"),
            (r"NO\.?1\b", "很受欢迎"), (r"TOP\.?1\b", "热门款"),
            # ① 权威/绝对性
            (r"顶级", "优质"), (r"极致", "精细"), (r"万能", "多用途"),
            (r"史无前例", "少见"), (r"国家级", "专业级"), (r"世界级", "高品质"),
            (r"100%有效", "效果不错"), (r"100%", "基本上"),
            # ① 模糊时限
            (r"随时涨价", ""), (r"抢疯了", "很受欢迎"), (r"仅此一次", ""),
            # ③ 虚假承诺
            (r"永久", "长期"), (r"零风险", "放心购"), (r"一洗白", "效果明显"),
            (r"稳赚不赔", "值得入手"), (r"包过", "效果好"),
            # ④ 迷信词
            (r"招财进宝", ""), (r"旺夫", ""), (r"旺宅", ""), (r"辟邪", ""),
            (r"逢凶化吉", ""),
            # ⑤ 拼音缩写
            (r"\bYYDS\b", "很棒"), (r"\byyds\b", "很棒"),
            (r"\bOMG\b", "哇"), (r"\bomg\b", "哇"),
            # ⑥ 医疗声称
            (r"防脱发", "呵护发丝"), (r"治愈脱发", "改善发量外观"),
            (r"修复发囊", ""), (r"治疗.{0,4}发", "改善发型"),
        ]
        for pattern, replacement in replacements:
            text = _re.sub(pattern, replacement, text)
        text = _re.sub(r"  +", " ", text).strip()
        return text

    def _parse_script_response(self, script_text: str, vibe: str) -> Dict:
        """解析Claude返回的脚本JSON，增强容错能力"""
        import re

        try:
            text = script_text

            # 1. 优先提取 markdown code block 内的 JSON
            code_block = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
            if code_block:
                text = code_block.group(1)

            # 2. 尝试直接找到第一个 { 到最后一个 } 的范围
            first_brace = text.find("{")
            last_brace = text.rfind("}")
            if first_brace >= 0 and last_brace > first_brace:
                candidate = text[first_brace:last_brace + 1]

                # 2a. 先试直接解析
                try:
                    script_json = json.loads(candidate)
                    if self._validate_script(script_json):
                        return self._finalize_script(script_json, vibe)
                except json.JSONDecodeError:
                    pass

                # 2b. 解析失败 → 尝试清理常见干扰（注释、尾随逗号等）
                cleaned = self._clean_json_string(candidate)
                if cleaned != candidate:
                    try:
                        script_json = json.loads(cleaned)
                        if self._validate_script(script_json):
                            return self._finalize_script(script_json, vibe)
                    except json.JSONDecodeError:
                        pass

                # 2c. 如果包含 "scenes" 但字段名有问题 → 尝试修复字段名
                if '"scenes"' in cleaned or '"scenes"' in candidate:
                    fixed = self._fix_json_fields(cleaned if cleaned != candidate else candidate)
                    if fixed:
                        try:
                            script_json = json.loads(fixed)
                            if self._validate_script(script_json):
                                return self._finalize_script(script_json, vibe)
                        except json.JSONDecodeError:
                            pass

            return self._fallback_script(vibe, reason="no valid JSON found in response")

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse script JSON: {e}")
            return self._fallback_script(vibe, reason=f"JSONDecodeError: {e}")

    def _finalize_script(self, script_json: Dict, vibe: str) -> Dict:
        """对成功解析的脚本做后处理"""
        if "scenes" in script_json:
            for scene in script_json["scenes"]:
                if scene.get("voiceover_text"):
                    scene["voiceover_text"] = self._sanitize_voiceover(scene["voiceover_text"])
        script_json.setdefault("vibe", vibe)
        script_json.setdefault("vibe_label", VIBE_CONFIGS.get(vibe, {}).get("label", vibe))
        return {
            "success": True,
            "script": script_json,
            "generated_at": time.time(),
        }

    def _clean_json_string(self, raw: str) -> str:
        """清理 JSON 字符串中的常见问题：尾随逗号、单引号键等"""
        import re as _re
        text = raw
        # 移除尾随逗号（在 } 或 ] 之前）
        text = _re.sub(r',\s*([}\]])', r'\1', text)
        # 尝试将单引号键转为双引号
        text = _re.sub(r"(?<=[{,])\s*'([^']+)'\s*:", r' "\1":', text)
        text = _re.sub(r":\s*'([^']*)'\s*(?=[,}\]])", r': "\1"', text)
        return text


    def _fix_json_fields(self, raw: str) -> Optional[str]:
        """尝试修复常见的 JSON 字段问题"""
        import re as _re
        text = raw
        # 修复未转义的中文引号
        text = _re.sub(r'"([^"]*)"', r'""', text)
        text = _re.sub(r'' + chr(8216) + '([^' + chr(8217) + ']*)' + chr(8217), r"''", text)
        # 修复缺失逗号（场景对象之间）
        text = _re.sub(r'(\})\s*(\{)', r'\1,\2', text)
        # 修复注释（// 或 # 开头的行）
        text = _re.sub(r'^\s*[#/].*$', '', text, flags=_re.MULTILINE)
        try:
            json.loads(text)
            return text
        except json.JSONDecodeError:
            return None

    def _validate_script(self, script: Dict) -> bool:
        """验证脚本结构完整性"""
        if not all(f in script for f in ["scenes", "total_duration"]):
            return False
        if not isinstance(script["scenes"], list) or not script["scenes"]:
            return False
        for scene in script["scenes"]:
            if not all(f in scene for f in ["scene_id", "voiceover_text", "timestamp_start"]):
                return False
        return True

    def _fallback_script(self, vibe: str = "trendy", reason: str = "JSON parse failed") -> Dict:
        """生成失败时的备用脚本"""
        vc = VIBE_CONFIGS.get(vibe, VIBE_CONFIGS["trendy"])
        return {
            "success": False,
            "error": reason,
            "script": {
                "vibe": vibe,
                "vibe_label": vc["label"],
                "script_type": "fallback",
                "narrative_structure": f"{vc['narrative']}（备用模板）",
                "total_duration": 55,
                "music_style": vc["music_style"],
                "pacing": vc["pacing"],
                "scenes": [
                    {
                        "scene_id": 1,
                        "timestamp_start": 0,
                        "timestamp_end": 8,
                        "scene_type": "hook",
                        "description": "强力开场，制造停留",
                        "voiceover_text": "等等！先别划走，就这一款假发，我研究了三个月才敢推",
                        "emotion": "excited",
                        "visual_requirements": ["手势拦截镜头", "假发近景特写"],
                        "camera_angle": "特写",
                        "transition": "快切",
                    },
                    {
                        "scene_id": 2,
                        "timestamp_start": 8,
                        "timestamp_end": 22,
                        "scene_type": "transformation",
                        "description": "蜕变对比，视觉冲击",
                        "voiceover_text": "你看，戴上之前和戴上之后，完全两个人！发量直接翻倍，自然到连闺蜜都以为是真发",
                        "emotion": "confident",
                        "visual_requirements": ["before/after对比镜头", "慢动作转身"],
                        "camera_angle": "中景",
                        "transition": "叠化",
                    },
                    {
                        "scene_id": 3,
                        "timestamp_start": 22,
                        "timestamp_end": 38,
                        "scene_type": "demonstration",
                        "description": "产品细节展示",
                        "voiceover_text": "发质超级细腻，你摸一下，真的和真发一模一样，不打结不变形，一梳就顺",
                        "emotion": "warm",
                        "visual_requirements": ["手指拨弄发丝特写", "梳头动作展示"],
                        "camera_angle": "特写",
                        "transition": "快切",
                    },
                    {
                        "scene_id": 4,
                        "timestamp_start": 38,
                        "timestamp_end": 47,
                        "scene_type": "promotion",
                        "description": "价格和活动",
                        "voiceover_text": "今天直播间专属价，原价三百多，今天只要这个数！库存不多了",
                        "emotion": "urgent",
                        "visual_requirements": ["价格字幕特效", "计时器动画"],
                        "camera_angle": "中景",
                        "transition": "快切",
                    },
                    {
                        "scene_id": 5,
                        "timestamp_start": 47,
                        "timestamp_end": 55,
                        "scene_type": "cta",
                        "description": "行动召唤",
                        "voiceover_text": "喜欢的宝子点击下方链接，马上冲！点赞收藏的姐妹我先谢谢了",
                        "emotion": "excited",
                        "visual_requirements": ["手指指向购物车", "笑容特写"],
                        "camera_angle": "中景",
                        "transition": "淡出",
                    },
                ],
                "emotional_arc": ["惊喜", "震撼", "心动", "冲动", "行动"],
                "key_messages": ["高仿真发质", "自然蓬松效果", "直播专属优惠"],
                "viral_hook": "等等！先别划走，就这一款假发，我研究了三个月才敢推",
                "call_to_action": "点击下方链接，限时特价，马上冲！",
                "style_notes": "使用备用模板，建议重新生成以获取个性化内容",
            },
            "generated_at": time.time(),
            "fallback": True,
        }
