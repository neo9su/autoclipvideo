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

logger = logging.getLogger(__name__)

# 复用现有配置
BEDROCK_URL = "https://bedrock-runtime.us-east-1.amazonaws.com"
BEDROCK_MODEL = os.environ.get("BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-6")


def _get_bedrock_token() -> str:
    return os.environ.get("AWS_BEARER_TOKEN_BEDROCK", "")

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
        "narrative": "吸引开场 → 产品亮点 → 使用效果 → 限量紧迫 → 催单收尾",
        "pacing": "fast",
        "scene_count_range": (6, 8),
        "music_style": "动感电子、节拍清晰",
        "default_scene_sequence": [
            "hook", "demonstration", "transformation", "social_proof", "urgency", "cta"
        ],
        "copywriting_style": "每句20~30字、句子饱满完整、自然口语、不叠词、每句话独立完整",
    },
}

# 场景类型说明（供 Claude 参考）
SCENE_TYPE_GUIDE = """
可用场景类型（从中选择最适合当前 vibe 的4-6个）：
- hook:          黄金开场钩子，3-5秒内吸引停留，可以是反问、悬念、强视觉
- problem:       痛点场景，展示目标用户的困扰（脱发、发量稀少、发型单调等）
- solution:      产品作为解决方案的出场，自然、流畅
- demonstration: 产品使用演示，展示效果、质感、佩戴体验
- social_proof:  社会认同，销量/口碑/达人推荐/用户评价
- transformation:蜕变对比，before→after，视觉冲击力最强
- promotion:     活动/价格/折扣，要有紧迫感但不生硬
- urgency:       限时/限量/库存告急，催单但不强迫
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

        headers = {
            "Authorization": f"Bearer {_get_bedrock_token()}",
            "Content-Type": "application/json",
        }

        payload = {
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
            "inferenceConfig": {
                "maxTokens": 5000,
                "temperature": 0.9,   # 更高创意度
            },
        }

        for attempt in range(1, 4):
            try:
                async with httpx.AsyncClient(timeout=90) as client:
                    response = await client.post(
                        f"{BEDROCK_URL}/model/{BEDROCK_MODEL}/converse",
                        json=payload,
                        headers=headers,
                    )

                if response.status_code == 200:
                    result = response.json()
                    script_text = result["output"]["message"]["content"][0]["text"]
                    return self._parse_script_response(script_text, vibe)
                elif response.status_code in (429, 500, 502, 503) and attempt < 3:
                    logger.warning(f"Bedrock {response.status_code}, retrying ({attempt}/3)...")
                else:
                    logger.error(f"Bedrock API error: {response.status_code} - {response.text[:300]}")
                    return self._fallback_script(vibe)

            except (httpx.ConnectError, httpx.TimeoutException) as e:
                if attempt < 3:
                    logger.warning(f"Bedrock transient error ({e}), retrying ({attempt}/3)...")
                else:
                    logger.error(f"Script generation failed after 3 attempts: {e}")
                    return self._fallback_script(vibe)
            except Exception as e:
                logger.error(f"Script generation failed: {e}")
                return self._fallback_script(vibe)

            await asyncio.sleep(2 ** attempt)

        return self._fallback_script(vibe)

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
2. 叙事结构：开场介绍产品是什么 → 讲外观/颜色/款式特点 → 演示效果/质感/戴法 → 适合人群/使用场景 → 引导关注
3. 每句话独立完整，能单独朗读出来让人听懂，不允许出现语义截断或上下文跳跃
4. 口语化但不用网络套话——禁止使用「等等等等」「你看你看」「注意注意」「哇哦」「OMG」「绝绝子」等无意义填充词
5. 不要有库存/断货/紧迫感等催单内容，除非直播录音里明确提到
6. 结尾统一用：「喜欢这款的姐妹记得点关注收藏，下次上新第一时间通知你！」

【节奏风格参考】{vc["label"]}：{vc["description"]}

请输出严格的JSON，不要有任何注释或前言，直接输出{{}}：

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
            "transition": "快切/淡入/叠化"
        }}
    ],
    "emotional_arc": ["场景1情绪"],
    "key_messages": ["卖点1", "卖点2"],
    "viral_hook": "开头第一句话",
    "call_to_action": "结尾行动召唤",
    "style_notes": "执行备注"
}}

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
2. 可以编造销量、好评、断货紧迫感，增加购买冲动
3. 每句话20~30字，句子要完整、饱满，不要过短，朗读出来至少需要3秒
4. 严禁叠词开场——不能用「等等等等」「你看你看」「哇哦哇哦」「姐妹姐妹」等重复词，每个词只说一次
5. 每个场景的配音是完整独立的一句话，朗读出来语义完整、不截断
6. 口语化，像朋友推荐，不像广告播音腔
7. 结尾固定用：「喜欢的姐妹，赶紧点小黄车，点关注不迷路！」

叙事顺序：产品亮相 → 外观/颜色/质感亮点 → 上头效果 → 销量/好评/断货 → 催单收尾

请输出严格的JSON，直接输出{{}}不要前言：

{{
    "vibe": "creative",
    "vibe_label": "自编文案",
    "script_type": "{script_type}",
    "narrative_structure": "创意叙事结构概述",
    "total_duration": 50,
    "music_style": "动感电子、节拍清晰",
    "pacing": "fast",
    "scenes": [
        {{
            "scene_id": 1,
            "timestamp_start": 0,
            "timestamp_end": 8,
            "scene_type": "hook",
            "description": "画面描述",
            "voiceover_text": "配音文案（完整一句话，15字以内）",
            "emotion": "confident",
            "visual_requirements": ["镜头描述"],
            "camera_angle": "特写/中景",
            "transition": "快切"
        }}
    ],
    "emotional_arc": ["场景情绪"],
    "key_messages": ["卖点1", "卖点2"],
    "viral_hook": "开头第一句",
    "call_to_action": "结尾召唤",
    "style_notes": "执行备注"
}}

场景数量：{min_scenes}~{max_scenes}个，emotion 从以下选择：
warm / clear / natural / persuasive / confident / urgent"""

    def _parse_script_response(self, script_text: str, vibe: str) -> Dict:
        """解析Claude返回的脚本JSON"""
        import re

        try:
            json_match = re.search(r"\{[\s\S]*\}", script_text)
            if json_match:
                script_json = json.loads(json_match.group())
                if self._validate_script(script_json):
                    # 确保 vibe 字段存在
                    script_json.setdefault("vibe", vibe)
                    script_json.setdefault("vibe_label", VIBE_CONFIGS.get(vibe, {}).get("label", vibe))
                    return {
                        "success": True,
                        "script": script_json,
                        "generated_at": time.time(),
                    }

            return self._fallback_script(vibe)

        except json.JSONDecodeError:
            logger.error("Failed to parse script JSON")
            return self._fallback_script(vibe)

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

    def _fallback_script(self, vibe: str = "trendy") -> Dict:
        """生成失败时的备用脚本"""
        vc = VIBE_CONFIGS.get(vibe, VIBE_CONFIGS["trendy"])
        return {
            "success": False,
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
