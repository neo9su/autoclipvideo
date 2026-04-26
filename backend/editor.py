"""
Intelligent clip editor for Douyin live recordings.

Pipeline:
  1. Parse SRT → scored segments
  2. Detect silence via ffmpeg → mark invalid
  3. Select best segments (15-30s total) with A-B-A structure
  4. Cut + concat via ffmpeg → output _clip.mp4
"""
import asyncio
import glob as _glob
import logging
import os
import random
import re
import tempfile
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), "..", "recordings")
MUSIC_DIR = os.path.join(os.path.dirname(__file__), "assets", "music")


def _pick_music() -> Optional[str]:
    tracks = [
        t for t in
        _glob.glob(os.path.join(MUSIC_DIR, "*.mp3")) +
        _glob.glob(os.path.join(MUSIC_DIR, "*.wav"))
        if not os.path.basename(t).startswith("_")  # skip auto-generated
    ]
    if tracks:
        return random.choice(tracks)
    # No user tracks: use auto-generated BGM library
    auto_tracks = [
        t for t in
        _glob.glob(os.path.join(MUSIC_DIR, "_bgm_*.mp3")) +
        _glob.glob(os.path.join(MUSIC_DIR, "_generated_bgm.mp3"))
        if os.path.exists(t)
    ]
    if auto_tracks:
        return random.choice(auto_tracks)
    try:
        from music_gen import generate_bgm
        return generate_bgm()
    except Exception as e:
        logger.warning(f"BGM generation failed: {e}")
        return None
CLIP_MIN = 30.0   # seconds (三段式叙事最短时长)
CLIP_MAX = 60.0   # seconds（抖音完播率最佳上限 60s，>60s 完播率明显下降）
MAX_CLIP_SEGMENTS = 50  # cap to avoid ffmpeg resource exhaustion
SEG_PAD = 0.0     # no padding — avoids duplicate audio at segment boundaries

# v2 引擎参数（发型边界识别模式）
CLIP_MIN_V2 = 46.0   # 抖音竖屏短视频最优完播区间下限
CLIP_MAX_V2 = 60.0   # 上限（抖音完播率最佳 ≤60s）

# ── Patterns that trigger segment removal ────────────────────────────────────
_REMOVE_PATTERNS = [
    r'\d+号链接',
    r'点.{0,3}链接',
    r'没货[了]?',
    r'有货的宝宝',
    r'下播',
    r'稍等[一下片刻]?',
    r'网络(卡顿?|问题|不好|断了?)',
    r'刷新[一下页面]?',
    r'黑屏',
    r'花屏',
    r'哪里人',
    r'吃饭(了|没)',
    r'今天怎么样',
    r'去拿[一下]?货',
    r'低头算',
    r'后台(操作|看[一下]?)',
    r'(尖锐|嘈杂)噪.?音',
    r'回声',
    # 催单
    r'最后\d+[百千]?单',
    r'抢最后',
    r'就剩\d+[百千]?单',
    r'仅剩\d+[百千]?单',
    r'秒没',
    # 催单 - 链接/下单
    r'[一二三四五六七八九十百]+号链接',
    r'拍[一二三四五六七八九十百\d]+号',
    r'(上|开)[了]?链接',
    r'赶(紧|快)(拍|下单)',
    r'截图.{0,5}下单',
    # 时间词
    r'这周|上周|下周',
    r'年前|年后',
    r'今天|明天|昨天',
    r'这个月|下个月|上个月',
    # 卖惨/演戏营销（巨量千川低质管控）
    r'快撑不下去',
    r'房租.{0,5}到期',
    r'老板.{0,5}(亏本|亏损)',
    r'清仓.{0,5}处理',
    r'(快|马上)倒闭',
    r'撑不住了',
    # 过度效果承诺（禁止承诺改变外貌）
    r'保证.{0,8}(变美|变好|显年轻)',
    r'显年轻\d+岁',
    r'遮住所有',
    r'彻底解决',
    # 诱骗互动（平台明确管控）
    r'点赞送礼',
    r'评论抽奖',
    r'转发有惊喜',
]

# ── Keyword scoring (higher = more valuable to keep) ─────────────────────────
_SCORES: dict[str, float] = {
    # ── 痛点（pain points）—— 片段必须选入 ────────────────────────────────────
    '发量少': 10, '发缝宽': 10, '发缝大': 10, '头顶塌': 10, '秃顶': 10, '秃头': 10,
    '贴头皮': 9, '显脸大': 9, '显老': 9, '稀疏': 9, '扁塌': 9, '扁头': 9,
    '油头塌': 9, '细软发': 9, '发际线高': 9, '头顶空': 10, '头型不好看': 9,
    '不敢低头': 9, '不敢扎头发': 9, '没自信': 8, '形象差': 8, '气质差': 8,
    '白发': 10, '遮白发': 11, '白头发': 10,
    '头发稀': 10, '发丝少': 10, '发量太少': 10, '头皮': 9, '油头': 8,
    '显白': 9,
    '出门快': 10, '五分钟': 10, '1分钟': 10, '一分钟': 10,
    '十五分钟': 9, '15分钟': 9, '省时': 9, '不用打理': 9, '每天都可以': 8,
    # 变化明显/瞬间变多/立刻蓬松 保留（视觉效果词）
    # 戴前/戴后/前后对比 已删除（巨量千川禁止佩戴前后对比暗示改变外貌）
    '变化明显': 10, '瞬间变多': 10, '立刻蓬松': 10,
    # ── 情绪刺激 / 社交证明（social proof）──────────────────────────────────
    '以为烫头': 10, '以为整容': 10, '同事以为': 10, '朋友以为': 9,
    '老公以为': 9, '男朋友以为': 9, '认不出来': 9, '以为变了': 8,
    '路人以为': 8, '都以为': 9, '以为去': 8,
    '大笑': 7, '惊讶': 7, '天啊': 7,
    # ── 产品核心卖点（product features）─────────────────────────────────────
    '自然': 7, '仿真头皮': 10, '无痕': 9, '看不出': 9, '真实感': 9,
    '蓬松': 9, '增加发量': 10, '遮盖发缝': 10, '高颅顶': 9,
    '显脸小': 9, '修饰脸型': 8,
    '真人发丝': 9, '递针': 8, '不掉色': 8, '免打理': 8,
    '仿真': 8, '一梳到底': 9, '秒变': 10, '小V脸': 10,
    '变身': 9, '背影杀': 9, '头包脸': 9, '氛围感': 8,
    # 产品参数
    '头围': 9, '大头围': 9, '小头围': 9,
    '人发': 8, '真人发': 9, '化纤': 7,
    '发根': 8, '发尾': 7,
    '色号': 8, '颜色': 7, '挑染': 8, '渐变色': 8,
    '学生头': 7, '梨花头': 7, 'bob头': 7, 'BOB头': 7,
    '短发': 7, '长发': 7, '卷发': 7, '直发': 7,
    # ── 佩戴过程（wearing process）───────────────────────────────────────────
    '一秒佩戴': 10, '快速戴上': 9, '新手可用': 9, '简单方便': 8,
    '不费时间': 9, '不挑人': 9, '轻松上手': 9,
    '戴上去': 8, '这样戴': 8, '夹一下': 7, '梳开': 7, '调整一下': 7,
    '戴好': 10, '套上去': 9, '摘下来': 8, '取下来': 8, '试试': 8, '试一下': 8,
    # ── 细节特写（detail closeup）—— 最高优先级 ──────────────────────────────
    '发缝真实': 11, '发根清晰': 11, '分缝自然': 11, '发丝细腻': 11,
    '贴合头皮': 10, '边缘自然': 10, '顺滑': 9, '不打结': 9,
    '不反光': 9, '颜色自然': 9,
    '特写': 11, '近景': 9, '细节': 11, '发丝质感': 12,
    '侧面': 10, '从侧面': 10, '侧边': 9, '正面': 8, '背面': 10,
    '后面': 9, '各个角度': 10,
    '整体': 7, '整体造型': 8, '全貌': 7,
    '头顶': 6, '顶部': 5, '俯视': 6,
    '360': 12, '转一圈': 11, '转一下': 7,
    # ── 身体部位细节（需放大对应区域）──────────────────────────────────────────
    '耳后': 11, '耳朵': 9, '耳边': 10, '耳侧': 10,
    '后脑勺': 11, '后脑': 10, '枕骨': 9, '后颈': 9,
    '鬓角': 11, '鬓边': 10, '两鬓': 10,
    '发际线': 10,
    '颈部': 8, '脖子': 8, '颈后': 9,
    '看这里': 9, '看这边': 9, '这个位置': 8, '放大': 10, '拉近': 10,
    # ── 舒适度（comfort）─────────────────────────────────────────────────────
    '透气': 8, '不闷': 9, '不勒头': 9, '轻薄': 8,
    '无负担': 8, '夏天可戴': 9, '久戴不累': 8,
    '怕热': 9, '夏天': 8, '夏日': 8, '网底': 9, '透气网': 9,
    '晒黑': 8, '戴着凉快': 9, '通风': 8, '散热': 7,
    # ── 稳固性（stability）───────────────────────────────────────────────────
    '不掉': 9, '不滑': 9, '不移位': 9, '卡扣固定': 9,
    '稳固贴合': 9, '牢固': 8, '跑步不掉': 10, '风吹不掉': 10,
    # ── 场景代入（usage scene）───────────────────────────────────────────────
    '上班': 8, '通勤': 8, '出门': 7, '约会': 9,
    '聚会': 8, '逛街': 8, '拍照': 7,
    '见客户': 8, '面试': 8, '相亲': 9, '婚礼': 8,
    '日常': 7, '懒人': 8, '早起赶时间': 9, '外出旅行': 8,
    '前任': 9, '见前任': 9, '见家长': 8, '毕业': 7,
    '男朋友': 8, '旅游': 8, '旅行': 8, '出游': 7, '早上': 6,
    # 场景对比（多场景展示）
    '室内': 5, '户外': 7, '室外': 7, '自然光': 8, '阳光下': 9,
    '室内室外': 10, '不同场景': 10, '换个场景': 9,
    '缩头': 8, '显头小': 9,
    # ── 转化引导（conversion CTA）────────────────────────────────────────────
    '炸福利': 10, '上车': 9, '运费险': 8,
    '不满意包退': 9, '包退': 8, '点购物车': 9, '加购': 7,
    '看到最后': 10, '一定要看': 10, '别划走': 10, '后面更夸张': 9,
    '真的有用': 8, '我放评论区了': 8, '链接在评论区': 8,
    '直接入': 9, '闭眼买': 9, '强烈推荐': 8,
    # ── 材质工艺（materials & craft）────────────────────────────────────────
    '全真发': 9, '哑光真发': 10, '顺削发': 9,
    '高仿真发丝': 11, '记忆丝': 9, '蛋白丝': 9,
    '蕾丝内网': 10, '全蕾丝': 10, '仿生头皮': 11,
    '递针工艺': 11, '单根勾织': 11, '仿生毛孔': 10,
    '防滑条': 8, '可调节扣': 8, '轻薄透气': 9,
    # ── 佩戴体验（wear comfort）──────────────────────────────────────────────
    '不闷汗': 9, '不扎头': 9, '无胶佩戴': 10,
    # ── 视觉效果（visual result）─────────────────────────────────────────────
    '一秒变发量': 12, '视觉增发': 11,
    '发际线逼真': 11, '无痕隐形': 11,
    '蓬松自然': 10, '不显头大': 9,
    '可随意分缝': 10, '发色均匀': 9, '无化学反光': 10,
    # ── 痛点补充（pain points extended）─────────────────────────────────────
    '细软塌': 9, '秃头星人': 10,
    '产后脱发': 10, '压力脱发': 9, '遗传性脱发': 10,
    'M型额头': 10, '秃鬓角': 10,
    '白发遮盖': 11, '不想染发': 9,
    '发型单调': 9, '不敢换造型': 9,
    '戴假发怕假': 10, '怕掉': 8, '怕闷': 8,
    '化疗': 10, '医疗性脱发': 10,
    # ── 场景补充（scene extended）────────────────────────────────────────────
    '日常通勤': 8, '上班上学': 8,
    '约会聚餐': 9, '同学聚会': 8,
    '婚礼敬酒': 9, '伴娘发型': 9,
    '舞台演出': 8, '年会活动': 8,
    '拍照上镜': 9, '短视频出镜': 8,
    # ── 转化补充（conversion extended）──────────────────────────────────────
    '真人发同效果': 10, '几分之一的价格': 10,
    '送全套工具': 9, '护理液': 8, '支架': 7,
    '7天试戴': 10, '首单优惠': 9, '直播间专属价': 10,
    '顺丰发货': 8, '隐私包装': 9,
    # ── 产品维护（maintenance）───────────────────────────────────────────────
    '不毛躁': 9, '少掉发': 9,
    '可烫可染': 10, '可修剪': 8, '可改短': 8,
    '送保养视频': 9, '终身护理建议': 10,
    '送防尘袋': 8, '发网': 8, '钢梳': 7,
}

# ── Segment category tags (10-category narrative system) ─────────────────────
# Narrative order: problem → comparison → social_proof → product → wearing →
#                  detail  → comfort    → result       → scene   → convert
_PROBLEM_KW = {
    '发量少', '发缝宽', '发缝大', '头顶塌', '秃顶', '秃头',
    '贴头皮', '显脸大', '显老', '稀疏', '扁塌', '扁头',
    '油头塌', '细软发', '发际线高', '头顶空', '头型不好看',
    '不敢低头', '不敢扎头发', '没自信', '形象差', '气质差',
    '白发', '遮白发', '白头发', '头发稀', '发丝少', '发量太少', '头皮', '油头',
    '出门快', '五分钟', '1分钟', '一分钟', '十五分钟', '15分钟', '省时', '不用打理',
    '细软塌', '秃头星人', '产后脱发', '压力脱发', '遗传性脱发',
    'M型额头', '秃鬓角', '白发遮盖', '不想染发',
    '发型单调', '不敢换造型', '戴假发怕假', '怕掉', '怕闷',
    '化疗', '医疗性脱发',
}
_COMPARISON_KW = {
    # 戴前/戴后/前后对比 已移除（巨量千川合规：不得展示佩戴前后对比）
    '变化明显', '瞬间变多', '立刻蓬松',
}
_SOCIAL_PROOF_KW = {
    '以为烫头', '以为整容', '同事以为', '朋友以为', '老公以为',
    '男朋友以为', '认不出来', '以为变了', '路人以为', '都以为', '以为去',
}
_PRODUCT_KW = {
    '仿真头皮', '无痕', '看不出', '真实感', '增加发量', '遮盖发缝',
    '高颅顶', '显脸小', '修饰脸型', '蓬松',
    '真人发丝', '递针', '不掉色', '免打理', '仿真', '一梳到底',
    '秒变', '小V脸', '变身', '背影杀', '头包脸', '氛围感',
    '头围', '大头围', '小头围', '人发', '真人发', '化纤',
    '发根', '发尾', '色号', '颜色', '挑染', '渐变色',
    '学生头', '梨花头', 'bob头', 'BOB头', '短发', '长发', '卷发', '直发',
    '全真发', '哑光真发', '顺削发', '高仿真发丝', '记忆丝', '蛋白丝',
    '蕾丝内网', '全蕾丝', '仿生头皮', '递针工艺', '单根勾织', '仿生毛孔',
    '防滑条', '可调节扣', '轻薄透气', '发色均匀', '无化学反光',
    '可烫可染', '可修剪', '可改短',
}
_WEARING_KW = {
    '一秒佩戴', '快速戴上', '新手可用', '简单方便', '不费时间', '不挑人', '轻松上手',
    '戴上去', '这样戴', '夹一下', '梳开', '调整一下',
    '戴好', '套上去', '摘下来', '取下来', '试试', '试一下',
}
_DETAIL_KW = {
    '发缝真实', '发根清晰', '分缝自然', '发丝细腻',
    '贴合头皮', '边缘自然', '顺滑', '不打结', '不反光', '颜色自然',
    '特写', '近景', '细节', '发丝质感',
    # 身体部位细节 → 分类为 detail，触发 push_in_strong
    '耳后', '耳边', '耳侧', '后脑勺', '后脑', '鬓角', '鬓边', '两鬓',
    '发际线', '颈后', '看这里', '看这边', '放大', '拉近',
}
_COMFORT_KW = {
    '透气', '不闷', '不勒头', '轻薄', '无负担', '夏天可戴', '久戴不累',
    '怕热', '夏天', '夏日', '网底', '透气网', '晒黑', '戴着凉快', '通风', '散热',
    '不掉', '不滑', '不移位', '卡扣固定', '稳固贴合', '牢固', '跑步不掉', '风吹不掉',
    '不闷汗', '不扎头', '无胶佩戴', '不显头大', '不毛躁',
}
_RESULT_KW = {
    '秒变', '小V脸', '变身', '高颅顶', '头包脸', '背影杀', '氛围感', '蓬松',
    '变化明显', '立刻蓬松', '瞬间变多',
    '一秒变发量', '视觉增发', '发际线逼真', '无痕隐形',
    '蓬松自然', '可随意分缝',
}
_SCENE_KW = {
    '上班', '通勤', '出门', '约会', '聚会', '逛街', '拍照',
    '见客户', '面试', '相亲', '婚礼', '日常', '懒人', '早起赶时间', '外出旅行',
    '前任', '见前任', '见家长', '毕业', '男朋友', '旅游', '旅行', '出游', '早上',
    '日常通勤', '上班上学', '约会聚餐', '同学聚会',
    '婚礼敬酒', '伴娘发型', '舞台演出', '年会活动',
    '拍照上镜', '短视频出镜',
    '室内', '户外', '室外', '自然光', '阳光下', '室内室外', '不同场景', '换个场景',
}
_CONVERT_KW = {
    '炸福利', '上车', '运费险', '包退', '点购物车', '加购',
    '看到最后', '一定要看', '别划走', '后面更夸张',
    '真的有用', '我放评论区了', '链接在评论区', '直接入', '闭眼买', '强烈推荐',
    '真人发同效果', '几分之一的价格', '送全套工具', '护理液', '支架',
    '7天试戴', '首单优惠', '直播间专属价', '顺丰发货', '隐私包装',
    '送保养视频', '终身护理建议', '送防尘袋', '发网', '钢梳', '少掉发',
}
# Legacy alias
_SOLUTION_KW = _PRODUCT_KW | _WEARING_KW

# Keyword → category mapping (used by segment_scorer.py)
_KW_TO_CAT: dict[str, str] = {}
for _kw in _PROBLEM_KW:       _KW_TO_CAT[_kw] = "problem"
for _kw in _COMPARISON_KW:    _KW_TO_CAT[_kw] = "comparison"
for _kw in _SOCIAL_PROOF_KW:  _KW_TO_CAT[_kw] = "social_proof"
for _kw in _PRODUCT_KW:       _KW_TO_CAT[_kw] = "product"
for _kw in _WEARING_KW:       _KW_TO_CAT[_kw] = "wearing"
for _kw in _DETAIL_KW:        _KW_TO_CAT[_kw] = "detail"
for _kw in _COMFORT_KW:       _KW_TO_CAT[_kw] = "comfort"
for _kw in _RESULT_KW:        _KW_TO_CAT[_kw] = "result"
for _kw in _SCENE_KW:         _KW_TO_CAT[_kw] = "scene"
for _kw in _CONVERT_KW:       _KW_TO_CAT[_kw] = "convert"
for _kw in _SCORES:
    if _kw not in _KW_TO_CAT:
        _KW_TO_CAT[_kw] = "neutral"

# Effective scoring table — _SCORES base + rule_overrides from DB applied at startup.
# score_and_tag() uses this dict so human-approved score changes take effect immediately.
_SCORES_EFFECTIVE: dict[str, float] = dict(_SCORES)


async def load_rule_overrides() -> int:
    """
    Load accepted rule overrides from the rule_overrides table and apply them
    to _SCORES_EFFECTIVE in-place.  Called once at server startup.
    Returns number of overrides applied.
    """
    try:
        import aiosqlite
        from db import DB_PATH
        async with aiosqlite.connect(DB_PATH, timeout=30) as db:
            async with db.execute("SELECT keyword, score FROM rule_overrides") as cur:
                rows = await cur.fetchall()
        applied = 0
        for kw, score in rows:
            _SCORES_EFFECTIVE[kw] = float(score)
            applied += 1
        if applied:
            logger.info(f"load_rule_overrides: applied {applied} overrides "
                        f"({', '.join(f'{kw}→{sc}' for kw, sc in rows)})")
        return applied
    except Exception as e:
        logger.warning(f"load_rule_overrides failed (non-fatal): {e}")
        return 0


@dataclass
class Seg:
    idx: int
    start: float
    end: float
    text: str
    score: float = 0.0
    valid: bool = True
    category: str = "neutral"   # problem/comparison/social_proof/product/wearing/detail/comfort/result/scene/convert/neutral
    motion: str = "static"      # camera motion style: push_in / push_in_strong / pull_out / pan_right / pan_left / tilt_up / tilt_down / static
    transition: str = "dissolve:0.35"  # xfade transition INTO this segment: "type:duration"
    reject_reason: str = ""     # why this seg was marked invalid (used by segment_scorer)

    @property
    def duration(self) -> float:
        return self.end - self.start


# ── ASS subtitle generation ────────────────────────────────────────────────────

# ── Font ──────────────────────────────────────────────────────────────────────
# Internal family name from the OTF (nameID=1 platformID=3)
_XQNT_FONT = "WenYue XinQingNianTi (Authorization Required) W8-J"

# ── Highlight keywords: product descriptors + scene nouns ─────────────────────
# ASS colors: &HAABBGGRR& (AA=00 opaque, bytes in B-G-R order)
# Warm gold #FFCC00 → R=FF G=CC B=00 → BGR 00,CC,FF → &H0000CCFF&
_HIGHLIGHT_COLOR = "&H0000CCFF&"   # warm gold

_HIGHLIGHT_PRODUCT: set[str] = {
    # 效果形容词
    '显白', '自然', '柔顺', '蓬松', '透气', '服帖', '轻盈', '轻薄',
    '减龄', '显年轻', '氛围感', '背影杀', '高颅顶', '小V脸', '头包脸',
    # 产品/工艺特性
    '真发', '仿真', '真人发丝', '递针', '无痕', '一梳到底',
    '不打结', '不起静电', '不脱色', '免打理', '全遮盖',
    # 视觉冲击
    '秒变', '变身',
}
_HIGHLIGHT_SCENE: set[str] = {
    '通勤', '派对', '同学会', '逛街', '约会', '婚礼',
    '拍照', '聚会', '旅游', '日常', '出行', '上班', '上课',
}
_HIGHLIGHT_ACTION: set[str] = {
    # 佩戴/安装步骤
    '分两份', '往里塞', '皮扣一勾', '防风扣', '固定好', '戴上去', '套上去',
    '扎球球', '别上去', '夹好', '梳顺', '摘下来', '取下来',
    # 造型操作
    '分缝', '拨开', '盘发', '卷发', '编发', '做造型',
    # 通用动作（足够长避免误匹配）
    '固定', '戴上', '套上', '梳开', '夹住', '扎起',
}
_HIGHLIGHT_PROMO: set[str] = {
    # 价格/促销
    '限时', '限量', '秒杀', '专属', '直播间价', '今天特价', '只要',
    '买一送一', '免费', '折扣', '优惠', '最低价', '史低', '清仓',
    '抢', '冲', '下单', '点链接', '立刻',
    # 效果承诺
    '包邮', '7天退', '无理由', '保证', '放心买',
}
_HIGHLIGHT_KW: set[str] = _HIGHLIGHT_PRODUCT | _HIGHLIGHT_SCENE | _HIGHLIGHT_ACTION | _HIGHLIGHT_PROMO

# Longest-first so "真人发丝" matches before "真发", "高颅顶" before "颅顶" etc.
_SORTED_HIGHLIGHT_KWS: list[str] = sorted(_HIGHLIGHT_KW, key=len, reverse=True)


# ── Gradient border constants (3-layer stacking) ──────────────────────────────
# Layer 0 (back)  : blue  outer ring bord=7, transparent fill
#   Blue  #0066FF → R=00 G=66 B=FF → BGR FF,66,00 → &H00FF6600&
# Layer 1 (middle): purple inner ring bord=4, transparent fill
#   Purple #8800FF → R=88 G=00 B=FF → BGR FF,00,88 → &H00FF0088&
# Layer 2 (front) : white text, thin dark border bord=2 + subtle shadow
_BORDER_BLUE   = r"{\1a&HFF&\3a&H80&\3c&H00FF6600&\bord8\shad0}"
_BORDER_PURPLE = r"{\1a&HFF&\3a&H80&\3c&H00FF0088&\bord5\shad0}"
_BORDER_TEXT   = r"{\3a&H80&\3c&H00141414&\bord2\shad1}"


# ── ASS subtitle style ────────────────────────────────────────────────────────
# Single consistent style — 新青年体, no built-in outline (handled by inline layer tags).
# (style_name, fontname, fontsize, bold, italic, spacing, outline, shadow)
_SUBTITLE_STYLES = [
    ("XQN",    _XQNT_FONT, 104, 0, 0, 1, 0, 0),   # 80 × 1.3 = 104
    # 右上角大艺术字：高亮关键词弹出层（Alignment=9 右上角，MarginR=60, MarginV=120）
    ("KWPOP",  _XQNT_FONT, 169, 1, 0, 0, 0, 0),   # 130 × 1.3 = 169
]

def _build_ass_styles() -> str:
    fmt = (
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
    )
    lines = [fmt]
    for name, font, size, bold, italic, spacing, outline, shadow in _SUBTITLE_STYLES:
        if name == "KWPOP":
            # 右上角大艺术字：金色，半透明描边，Alignment=9（右上），MarginR=60，MarginV=120
            lines.append(
                f"Style: {name},{font},{size},"
                f"&H0000CCFF,&H000000FF,&H80141414,&H80000000,"
                f"{bold},{italic},0,0,100,100,{spacing},0,1,6,4,9,0,60,120,1\n"
            )
        else:
            lines.append(
                f"Style: {name},{font},{size},"
                f"&H00FFFFFF,&H000000FF,&H80141414,&H80000000,"
                f"{bold},{italic},0,0,100,100,{spacing},0,1,{outline},{shadow},2,80,80,120,1\n"
            )
    return "".join(lines)


_ASS_HEADER_BASE = """\
[Script Info]
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1440
PlayResY: 2560

[V4+ Styles]
"""

def _make_ass_header() -> str:
    return _ASS_HEADER_BASE + _build_ass_styles() + "\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"


def _sec_to_ass(s: float) -> str:
    s = max(0.0, s)
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    return f"{h}:{m:02d}:{sec:05.2f}"


def _annotate_text(text: str) -> tuple[str, bool]:
    """Wrap highlight keywords in gold+bold ASS tags. Returns (tagged_text, had_keyword)."""
    has_kw = False
    for kw in _SORTED_HIGHLIGHT_KWS:
        if kw in text:
            open_tag  = "{\\c" + _HIGHLIGHT_COLOR + "\\b1}"
            close_tag = "{\\r}"
            text = text.replace(kw, open_tag + kw + close_tag, 1)
            has_kw = True
    return text, has_kw


_ANIM_STYLES = [
    # style 1: gentle scale pulse
    r"{\fad(120,80)\t(0,300,\fscx105\fscy105)\t(300,600,\fscx100\fscy100)}",
    # style 2: soft scale
    r"{\fad(100,80)\t(0,200,\fscx102\fscy102)\t(200,400,\fscx100\fscy100)}",
    # style 3: bounce
    r"{\fad(80,60)\t(0,150,\fscx108\fscy108)\t(150,300,\fscx97\fscy97)\t(300,450,\fscx103\fscy103)\t(450,600,\fscx100\fscy100)}",
    # style 4: fill flash gold→white on entrance
    r"{\fad(100,80)\t(0,300,\c&H0000CCFF&)\t(300,600,\c&H00FFFFFF&)}",
]
# Keyword lines: bigger pop + keep animation synced across all 3 layers
_ANIM_KW = r"{\fad(150,100)\t(0,200,\fscx112\fscy112)\t(200,400,\fscx100\fscy100)}"


# Cache the ASS header — it never changes between clips.
_ASS_HEADER: str = _make_ass_header()


def build_ass(selected: List[Seg], all_segs: List[Seg]) -> str:
    """
    Generate ASS subtitle string with 3-layer gradient border.

    Each SRT line becomes 3 stacked Dialogue events:
      Layer 0: blue  outer ring (bord=7, transparent fill)
      Layer 1: purple inner ring (bord=4, transparent fill)
      Layer 2: white text       (bord=2, thin dark outline)

    Highlight keywords on Layer 2 are coloured warm-gold + bold.
    """
    MAX_SUB_CHARS = 14  # 每屏最多14字，超出则截断（保留完整词）

    def _truncate(text: str) -> str:
        """Keep at most MAX_SUB_CHARS characters."""
        return text[:MAX_SUB_CHARS] if len(text) > MAX_SUB_CHARS else text

    header = _ASS_HEADER
    dialogue: list[str] = []
    cursor = 0.0
    line_idx = 0
    rendered_srt_ids: set = set()   # track (srt.idx, sel_seg_idx) to avoid duplicates
    for sel_idx, sel_seg in enumerate(selected):
        offset = cursor
        cursor += sel_seg.duration  # SEG_PAD=0, no padding
        for srt in all_segs:
            ov_start = max(srt.start, sel_seg.start)
            ov_end   = min(srt.end,   sel_seg.end)
            if ov_end - ov_start < 0.15:  # require at least 150ms overlap
                continue
            dedup_key = (srt.idx, sel_idx)
            if dedup_key in rendered_srt_ids:
                continue
            rendered_srt_ids.add(dedup_key)
            t0 = offset + (ov_start - sel_seg.start)
            t1 = offset + (ov_end   - sel_seg.start)
            raw_text = _truncate(srt.text)
            annotated, has_kw = _annotate_text(raw_text)
            anim = _ANIM_KW if has_kw else _ANIM_STYLES[line_idx % len(_ANIM_STYLES)]
            line_idx += 1
            ts0, ts1 = _sec_to_ass(t0), _sec_to_ass(t1)
            # Layer 0: white text + keyword highlights (半透明深色描边，无蓝/紫色)
            dialogue.append(f"Dialogue: 0,{ts0},{ts1},XQN,,0,0,0,,{anim}{_BORDER_TEXT}{annotated}")
            # Layer 3: 右上角关键词大艺术字弹出（仅含高亮词的句子）
            if has_kw:
                kw_match = next((kw for kw in _SORTED_HIGHLIGHT_KWS if kw in raw_text), None)
                if kw_match:
                    kw_anim = (r"{\fad(0,200)"
                               r"\t(0,150,\fscx130\fscy130)"
                               r"\t(150,300,\fscx95\fscy95)"
                               r"\t(300,450,\fscx108\fscy108)"
                               r"\t(450,600,\fscx100\fscy100)}")
                    dialogue.append(
                        f"Dialogue: 3,{ts0},{ts1},KWPOP,,0,0,0,,{kw_anim}{kw_match}"
                    )
    return header + "\n".join(dialogue) + "\n"


FADE_DUR = 1.5       # video-to-video direct crossfade (seconds)
ANIME_FADE = 0.5     # crossfade into/out of anime transition frame
ANIME_TOTAL = 2.0    # total duration of anime still input (includes both fades)

# Output resolution: 2K portrait (9:16)
OUT_W = 1080
OUT_H = 1920

# ComfyUI input resolution: SD1.5-safe portrait (9:16), avoids VRAM OOM at 4K
COMFY_W = 576   # 9:16 portrait, divisible by 64 (SD 1.5 requirement)
COMFY_H = 1024

# Zoom punch: 1.5× crop toward face/wig area (upper-centre of frame)
ZOOM_FACTOR = 1.5
ZOOM_W = int(OUT_W / ZOOM_FACTOR)   # 1440
ZOOM_H = int(OUT_H / ZOOM_FACTOR)   # 2560
ZOOM_X = (OUT_W - ZOOM_W) // 2      # 360 – centred horizontally
ZOOM_Y = 0                           # start from top → captures face/wig

# Fallback transition pool — used when a segment has no assigned transition.
# Includes slide/zoom effects for more dynamic feels.
_TR_POOL = [
    "slideleft",   # 滑移
    "zoomin",      # 聚焦
    "squeezeh",    # 画中画
    "fadeblack",   # 人物重叠
    "slideright",  # 滑移反向
    "radial",      # 聚焦放射
    "hblur",       # 运动模糊
    "squeezev",    # 画中画竖
    "dissolve",    # 叠加
    "wipeleft",    # 擦入
]

# Map style-assigned transition names to valid ffmpeg xfade transitions.
# Custom names (phone_zoom, shadow_sweep, etc.) get mapped here.
_TR_REMAP: dict[str, str] = {
    "phone_zoom":    "zoomin",       # 手机放大 → zoom聚焦
    "shadow_sweep":  "fadeblack",    # 阴影扫过
    "polaroid":      "fadewhite",    # 拍立得闪白
    "camera_zoomout":"fadewhite",    # 镜头拉远
    "center_fade":   "dissolve",     # 中心淡入
    "pixel_dissolve":"pixelize",     # 像素溶解
    "diagonal_wipe": "diagtl",       # 对角擦入
    "zoom_punch":    "dissolve",     # 由 _gen_zoom_punch_clips 处理，xfade用dissolve
}


def _motion_vf(seg: Seg, w: int = OUT_W, h: int = OUT_H) -> str:
    """Return a ffmpeg vf filter string that applies the segment's camera motion."""
    base = (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
    )
    sharp = "unsharp=5:5:0.8:5:5:0.0"
    motion = seg.motion
    dur = max(seg.duration, 1.0)
    fps = 25
    n = int(dur * fps)

    if motion in ("push_in", "push_in_strong"):
        # 缓慢推进放大：1.0x → 1.12x（push_in）or 1.0x → 1.20x（push_in_strong，细节放大）
        end_zoom = 1.20 if motion == "push_in_strong" else 1.12
        # zoompan: zoom from 1.0 to end_zoom, centered on upper-center (face/wig)
        zp = (
            f"zoompan=z='min(1+({end_zoom-1:.3f})*on/{n},  {end_zoom:.3f})':"
            f"x='(iw/2)-(iw/zoom/2)':y='(ih*0.3)-(ih/zoom*0.3)':"
            f"d={n}:s={w}x{h}:fps={fps}"
        )
        return f"{base},{zp},{sharp}"
    elif motion == "pull_out":
        # 缓慢拉远：1.12x → 1.0x
        start_zoom = 1.12
        zp = (
            f"zoompan=z='max({start_zoom:.3f}-({start_zoom-1:.3f})*on/{n}, 1.0)':"
            f"x='(iw/2)-(iw/zoom/2)':y='(ih*0.3)-(ih/zoom*0.3)':"
            f"d={n}:s={w}x{h}:fps={fps}"
        )
        return f"{base},{zp},{sharp}"
    elif motion == "pan_right":
        # 从左向右缓慢平移
        zp = (
            f"zoompan=z=1.08:"
            f"x='(iw/2 - iw/zoom/2) + (iw/zoom*0.05)*on/{n}':"
            f"y='(ih*0.3)-(ih/zoom*0.3)':"
            f"d={n}:s={w}x{h}:fps={fps}"
        )
        return f"{base},{zp},{sharp}"
    elif motion == "pan_left":
        zp = (
            f"zoompan=z=1.08:"
            f"x='(iw/2 - iw/zoom/2) - (iw/zoom*0.05)*on/{n}':"
            f"y='(ih*0.3)-(ih/zoom*0.3)':"
            f"d={n}:s={w}x{h}:fps={fps}"
        )
        return f"{base},{zp},{sharp}"
    elif motion == "tilt_up":
        zp = (
            f"zoompan=z=1.06:"
            f"x='(iw/2)-(iw/zoom/2)':"
            f"y='(ih*0.4 - ih/zoom*0.4) - (ih/zoom*0.06)*on/{n}':"
            f"d={n}:s={w}x{h}:fps={fps}"
        )
        return f"{base},{zp},{sharp}"
    elif motion == "tilt_down":
        zp = (
            f"zoompan=z=1.06:"
            f"x='(iw/2)-(iw/zoom/2)':"
            f"y='(ih*0.3 - ih/zoom*0.3) + (ih/zoom*0.06)*on/{n}':"
            f"d={n}:s={w}x{h}:fps={fps}"
        )
        return f"{base},{zp},{sharp}"
    else:
        # static — no motion
        return f"{base},fps={fps},{sharp}"


async def _preprocess_segments(mp4: str, selected: List[Seg], tmp_dir: str, on_progress=None) -> List[Optional[str]]:
    """Pre-encode each segment to 4K temp file in parallel to reduce filter-graph memory.
    Audio: apply noisereduce (voice isolation) when available, else ffmpeg-only denoising.
    Video: lanczos upscale + motion filter (zoom/pan per segment) + sharpening.
    """

    from denoise import extract_and_denoise

    async def _one(i: int, seg: Seg) -> Optional[str]:
        out = os.path.join(tmp_dir, f"seg{i}.mp4")
        pad_b = min(SEG_PAD, seg.start)   # pre-buffer (clamped so we don't seek before t=0)
        pad_a = SEG_PAD                    # post-buffer
        audio_start = seg.start - pad_b
        padded_dur  = seg.duration + pad_b + pad_a

        pre = max(0.0, audio_start - 3.0)
        fs  = audio_start - pre
        fe  = fs + padded_dur
        duration = padded_dur + 0.1

        # Noisereduce audio covers the full padded window so it stays aligned with video.
        denoised_wav = os.path.join(tmp_dir, f"seg{i}_dn.wav")
        has_denoised = await extract_and_denoise(mp4, audio_start, padded_dur + 0.15, denoised_wav)

        motion_vf = _motion_vf(seg)

        if has_denoised:
            cmd = [
                "ffmpeg", "-y",
                "-ss", f"{pre:.3f}", "-i", mp4,
                "-i", denoised_wav,
                "-vf", f"trim={fs:.3f}:{fe:.3f},setpts=PTS-STARTPTS,{motion_vf}",
                "-map", "0:v", "-map", "1:a",
                "-t", f"{duration:.3f}",
                "-c:v", "h264_videotoolbox", "-b:v", "10M", "-allow_sw", "1",
                "-c:a", "aac", "-b:a", "128k",
                out,
            ]
        else:
            # Fallback: ffmpeg-only chain — highpass + aggressive afftdn + anlmdn
            af = (
                f"atrim={fs:.3f}:{fe:.3f},asetpts=PTS-STARTPTS,"
                "highpass=f=100,"
                "afftdn=nf=-40:nt=w,"
                "anlmdn=s=7:p=0.002:r=0.002:m=15"
            )
            cmd = [
                "ffmpeg", "-y", "-ss", f"{pre:.3f}", "-i", mp4,
                "-vf", f"trim={fs:.3f}:{fe:.3f},setpts=PTS-STARTPTS,{motion_vf}",
                "-af", af,
                "-t", f"{duration:.3f}",
                "-c:v", "h264_videotoolbox", "-b:v", "10M", "-allow_sw", "1",
                "-c:a", "aac", "-b:a", "128k",
                out,
            ]

        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        await proc.communicate()
        try:
            os.remove(denoised_wav)
        except Exception:
            pass
        if proc.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0:
            return out
        logger.warning(f"Pre-encode failed for segment {i}")
        return None

    # 1 concurrent pre-encode per clip job; with MAX_CONCURRENT_CLIPS=2 this means
    # at most 2 parallel 4K ffmpeg pre-encodes system-wide, avoiding OOM
    sem = asyncio.Semaphore(1)

    n_segs = len(selected)

    async def _one_sem(i: int, seg: Seg) -> Optional[str]:
        async with sem:
            logger.debug(f"Pre-encoding segment {i+1}/{n_segs} ...")
            result = await _one(i, seg)
            if on_progress:
                await on_progress("preprocess", i + 1, n_segs)
            return result

    results = await asyncio.gather(*[_one_sem(i, seg) for i, seg in enumerate(selected)])
    return list(results)


async def _xfade_merge(
    seg_files: List[str],
    selected: List[Seg],
    boundary_frames: dict,
    tmp_dir: str,
    seg_durations: Optional[List[float]] = None,
    on_progress=None,
) -> Tuple[Optional[str], float]:
    """Tree-based parallel xfade merge with asyncio.Semaphore(2).

    Merges in O(log N) rounds; up to 2 concurrent ffmpeg processes per round.
    Memory stays bounded (each process reads exactly 2 inputs) while wall-clock
    time is roughly halved vs. the previous linear approach for large N.

    boundary_frames: {bi: jpeg/png_path} for anime/zoom_punch transitions.
    Returns (merged_path, total_duration) or (None, 0.0) on failure.
    """
    n = len(seg_files)
    if n == 0:
        return None, 0.0
    if n == 1:
        return seg_files[0], selected[0].duration

    _SF = (
        f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease,"
        f"pad={OUT_W}:{OUT_H}:(ow-iw)/2:(oh-ih)/2"
    )
    sem = asyncio.Semaphore(1)   # one merge at a time: each xfade buffers two 4K streams in RAM
    _counter = [0]

    async def _run(cmd: list) -> Tuple[int, str]:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        _, err = await proc.communicate()
        return proc.returncode, err.decode(errors="replace")

    async def _merge2(f1: str, f2: str, tr: str, offset: float, dst: str) -> bool:
        rc, err = await _run([
            "ffmpeg", "-y", "-i", f1, "-i", f2,
            "-filter_complex",
            f"[0:v]settb=1/25[va];[1:v]settb=1/25[vb];"
            f"[va][vb]xfade=transition={tr}:duration={FADE_DUR}:offset={offset:.3f}[vout];"
            f"[0:a][1:a]acrossfade=d={FADE_DUR}[aout]",
            "-map", "[vout]", "-map", "[aout]",
            "-pix_fmt", "yuv420p",
            "-c:v", "h264_videotoolbox", "-b:v", "8M", "-allow_sw", "1",
            "-c:a", "aac", "-b:a", "128k",
            dst,
        ])
        if rc != 0:
            logger.error(f"_merge2 rc={rc}: {err[-400:]}")
        return rc == 0

    async def _merge_anime(f1: str, anime: str, f2: str, tr: str, fade_off: float, dst: str) -> bool:
        """3-step: f1 → fadewhite → anime_still (with Ken Burns zoom) → tr-xfade → f2"""
        tmp1 = dst + "_s1.mp4"
        _n_frames = int(ANIME_TOTAL * 25)   # total frames for zoompan duration
        # Ken Burns: slow zoom from 1.0× to ~1.11× centered on upper-center (face area)
        _anime_vf = (
            f"scale={COMFY_W}:{COMFY_H}:force_original_aspect_ratio=decrease,"
            f"pad={COMFY_W}:{COMFY_H}:(ow-iw)/2:(oh-ih)/2,"
            f"fps=25,"
            f"zoompan=z='min(zoom+0.0022,1.11)':d={_n_frames}"
            f":x='(iw/2)-(iw/zoom/2)':y='(ih/3)-(ih/zoom/3)'"
            f":s={COMFY_W}x{COMFY_H},"
            f"scale={OUT_W}:{OUT_H}:flags=lanczos,"
            f"unsharp=5:5:0.4:5:5:0.0,"
            f"settb=1/25"
        )
        rc1, err1 = await _run([
            "ffmpeg", "-y", "-i", f1,
            "-loop", "1", "-t", f"{ANIME_TOTAL:.1f}", "-i", anime,
            "-filter_complex",
            f"[0:v]settb=1/25[va];"
            f"[1:v]{_anime_vf}[vb];"
            f"[va][vb]xfade=transition=fadewhite:duration={ANIME_FADE}:offset={fade_off:.3f}[vout];"
            f"aevalsrc=0:c=stereo:s=44100,atrim=duration={ANIME_TOTAL:.1f},asetpts=PTS-STARTPTS[asilent];"
            f"[0:a][asilent]acrossfade=d={ANIME_FADE}[aout]",
            "-map", "[vout]", "-map", "[aout]",
            "-pix_fmt", "yuv420p",
            "-c:v", "h264_videotoolbox", "-b:v", "8M", "-allow_sw", "1",
            "-c:a", "aac", "-b:a", "128k",
            tmp1,
        ])
        if rc1 != 0:
            logger.error(f"_merge_anime step1 rc={rc1}: {err1[-300:]}")
            return False
        step2_off = fade_off + ANIME_TOTAL - ANIME_FADE
        rc2, err2 = await _run([
            "ffmpeg", "-y", "-i", tmp1, "-i", f2,
            "-filter_complex",
            f"[0:v]settb=1/25[va];[1:v]settb=1/25[vb];"
            f"[va][vb]xfade=transition={tr}:duration={ANIME_FADE}:offset={step2_off:.3f}[vout];"
            f"[0:a][1:a]acrossfade=d={ANIME_FADE}[aout]",
            "-map", "[vout]", "-map", "[aout]",
            "-pix_fmt", "yuv420p",
            "-c:v", "h264_videotoolbox", "-b:v", "15M", "-allow_sw", "1",
            "-c:a", "aac", "-b:a", "128k",
            dst,
        ])
        try:
            os.remove(tmp1)
        except Exception:
            pass
        if rc2 != 0:
            logger.error(f"_merge_anime step2 rc={rc2}: {err2[-300:]}")
        return rc2 == 0

    async def _do_merge(left: tuple, right: tuple) -> Optional[tuple]:
        """Merge two chunks under the semaphore; returns new chunk or None."""
        async with sem:
            lf, ldur, llorig, lrorig, ltemp = left
            rf, rdur, rlorig, rrorig, rtemp = right
            bi = lrorig  # boundary index = rightmost original seg of left chunk
            # Use per-segment assigned transition (set by _assign_styles); fall back to pool.
            next_idx = bi + 1
            if next_idx < len(selected) and selected[next_idx].transition:
                raw_tr = selected[next_idx].transition.split(":")[0]
                tr = _TR_REMAP.get(raw_tr, raw_tr)
            else:
                tr = _TR_POOL[bi % len(_TR_POOL)]
            xfade_tr = _TR_REMAP.get(tr, tr)
            _counter[0] += 1
            dst = os.path.join(tmp_dir, f"tree_{_counter[0]}.mp4")

            if bi in boundary_frames:
                fade_off = ldur - ANIME_FADE
                ok = await _merge_anime(lf, boundary_frames[bi], rf, xfade_tr, fade_off, dst)
                new_dur = fade_off + ANIME_TOTAL - ANIME_FADE + rdur
            else:
                xfade_off = max(0.0, ldur - FADE_DUR)
                ok = await _merge2(lf, rf, xfade_tr, xfade_off, dst)
                new_dur = ldur - FADE_DUR + rdur

            if ltemp:
                try:
                    os.remove(lf)
                except Exception:
                    pass
            if rtemp:
                try:
                    os.remove(rf)
                except Exception:
                    pass
            if not ok:
                return None
            return (dst, new_dur, llorig, rrorig, True)

    # Each chunk: (file, duration, left_orig_idx, right_orig_idx, is_temp)
    # Use provided padded durations if available, else fall back to Seg.duration
    _durations = seg_durations if (seg_durations and len(seg_durations) == n) else [s.duration for s in selected]
    chunks: List[tuple] = [
        (seg_files[i], _durations[i], i, i, False) for i in range(n)
    ]

    import math as _math
    total_rounds = _math.ceil(_math.log2(n)) if n > 1 else 1
    round_num = 0
    while len(chunks) > 1:
        round_num += 1
        next_chunks: List[Optional[tuple]] = []
        merge_tasks: List[Tuple[int, tuple, tuple]] = []  # (slot, left, right)

        for j in range(0, len(chunks), 2):
            if j + 1 >= len(chunks):
                next_chunks.append(chunks[j])  # odd chunk carries forward
            else:
                next_chunks.append(None)        # placeholder for merge result
                merge_tasks.append((len(next_chunks) - 1, chunks[j], chunks[j + 1]))

        results = await asyncio.gather(*[_do_merge(l, r) for _, l, r in merge_tasks])

        for (slot, _, _), res in zip(merge_tasks, results):
            if res is None:
                return None, 0.0
            next_chunks[slot] = res

        chunks = next_chunks  # type: ignore
        logger.debug(f"Tree merge round {round_num}: {len(chunks)} chunk(s) remaining")
        if on_progress:
            await on_progress("merge", round_num, total_rounds)

    return chunks[0][0], chunks[0][1]


async def _build_clip(
    mp4: str,
    selected: List[Seg],
    segs: List[Seg],
    out: str,
    anime_frames: Optional[List[Optional[str]]] = None,
    person_frames: Optional[dict] = None,
    zoom_punch_clips: Optional[dict] = None,
    on_progress=None,
) -> bool:
    """Three-phase pipeline to avoid OOM on 8 GB RAM with many 4K segments:
      Phase 1: sequential pre-encode each segment to 4K temp file
      Phase 2: iterative pairwise xfade merge (constant 2-input memory per step)
      Phase 3: final pass – subtitles + background music
    """
    n = len(selected)
    ass_content = build_ass(selected, segs)
    has_subs = "Dialogue:" in ass_content

    with tempfile.TemporaryDirectory() as tmp:
        ass_path = os.path.join(tmp, "subs.ass")
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)

        # ── Phase 1: sequential pre-encode to 4K ──────────────────────────────
        if on_progress:
            await on_progress("preprocess", 0, n)
        seg_files = await _preprocess_segments(mp4, selected, tmp, on_progress=on_progress)
        if any(f is None for f in seg_files):
            logger.error("Pre-encode failed for one or more segments")
            return False

        # Actual padded duration of each pre-encoded segment (includes SEG_PAD on both sides)
        seg_durations = [
            seg.duration + min(SEG_PAD, seg.start) + SEG_PAD
            for seg in selected
        ]

        # Build boundary frame mapping (anime takes priority over zoom_punch)
        boundary_frames: dict = {}
        for bi in range(n - 1):
            af = anime_frames[bi] if anime_frames and bi < len(anime_frames) else None
            zf = zoom_punch_clips.get(bi) if zoom_punch_clips else None
            frame = af or zf
            if frame:
                boundary_frames[bi] = frame

        # ── Phase 2: iterative pairwise xfade merge ────────────────────────────
        if on_progress:
            await on_progress("merge", 0, 1)
        merged_file, _merged_dur = await _xfade_merge(
            seg_files, selected, boundary_frames, tmp,
            seg_durations=seg_durations, on_progress=on_progress
        )
        if merged_file is None:
            logger.error("Iterative xfade merge failed")
            return False

        # ── Phase 3: final encode – subtitles + music ─────────────────────────
        if on_progress:
            await on_progress("final", 0, 1)
        music_path = _pick_music()
        cmd = ["ffmpeg", "-y", "-i", merged_file]
        parts: List[str] = []
        music_idx: Optional[int] = None

        if music_path:
            cmd += ["-stream_loop", "-1", "-i", music_path]
            music_idx = 1
            parts.append(
                # Compress voice, normalize loudness, force stereo before mixing
                f"[0:a]acompressor=threshold=-25dB:ratio=3:attack=5:release=100:makeup=4dB,"
                f"loudnorm=I=-16:TP=-1.5:LRA=11,"
                f"aformat=channel_layouts=stereo[voice];"
                f"[{music_idx}:a]volume=0.40,aformat=channel_layouts=stereo[bgm];"
                f"[voice][bgm]amix=inputs=2:duration=first:normalize=0[aout]"
            )
            audio_map = "[aout]"
        else:
            # No music: still normalise voice loudness
            parts.append(
                "[0:a]acompressor=threshold=-25dB:ratio=3:attack=5:release=100:makeup=4dB,"
                "loudnorm=I=-16:TP=-1.5:LRA=11,"
                "aformat=channel_layouts=stereo[aout]"
            )
            audio_map = "[aout]"

        if has_subs:
            escaped = ass_path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
            parts.append(f"[0:v]ass={escaped}[vout]")
            vmap = "[vout]"
        else:
            vmap = "0:v"

        if parts:
            cmd += ["-filter_complex", ";".join(parts)]

        cmd += [
            "-map", vmap, "-map", audio_map,
            "-pix_fmt", "yuv420p",
            "-c:v", "h264_videotoolbox", "-b:v", "10M", "-allow_sw", "1",
            "-ar", "44100", "-ac", "2",
            "-c:a", "aac", "-b:a", "192k",
            out,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        ok = proc.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0
        if not ok:
            decoded = stderr.decode(errors="replace")
            logger.error(f"_build_clip final encode rc={proc.returncode}")
            logger.error(f"_build_clip stderr:\n{decoded[-2000:]}")
        return ok


async def _prepend_thumbnail(clip_path: str, thumb_path: str) -> bool:
    """
    Prepend `thumb_path` as a 0.5-second still frame at the beginning of `clip_path`.
    Two-step: encode JPEG → 0.5s mp4, then concat with clip via demuxer (-c copy).
    Overwrites the original file in-place.
    """
    tmp_thumb = clip_path + "_thumb0.mp4"
    tmp_out   = clip_path + ".prepend_tmp.mp4"
    list_file = clip_path + "_concat.txt"

    try:
        # Step 1: encode thumbnail JPEG → 0.5s mp4 (same codec as clip)
        _SF = (
            f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease,"
            f"pad={OUT_W}:{OUT_H}:(ow-iw)/2:(oh-ih)/2,fps=25"
        )
        cmd1 = [
            "ffmpeg", "-y",
            "-loop", "1", "-t", "0.5", "-i", thumb_path,
            "-f", "lavfi", "-t", "0.5", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-vf", _SF,
            "-c:v", "h264_videotoolbox", "-b:v", "10M", "-allow_sw", "1",
            "-c:a", "aac", "-b:a", "128k",
            tmp_thumb,
        ]
        p1 = await asyncio.create_subprocess_exec(
            *cmd1, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        _, err1 = await p1.communicate()
        if p1.returncode != 0 or not os.path.exists(tmp_thumb):
            logger.warning(f"_prepend_thumbnail step1 failed: {err1.decode()[-300:]}")
            return False

        # Step 2: concat via demuxer with -c copy (no re-encode of the clip)
        with open(list_file, "w") as f:
            f.write(f"file '{tmp_thumb}'\n")
            f.write(f"file '{clip_path}'\n")

        cmd2 = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", list_file,
            "-c", "copy",
            tmp_out,
        ]
        p2 = await asyncio.create_subprocess_exec(
            *cmd2, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        _, err2 = await p2.communicate()
        ok = p2.returncode == 0 and os.path.exists(tmp_out) and os.path.getsize(tmp_out) > 0
        if ok:
            os.replace(tmp_out, clip_path)
            logger.info(f"Thumbnail prepended (0.5s) to {os.path.basename(clip_path)}")
        else:
            logger.warning(f"_prepend_thumbnail step2 failed: {err2.decode()[-400:]}")
            if os.path.exists(tmp_out):
                os.remove(tmp_out)
        return ok

    finally:
        for p in (tmp_thumb, list_file):
            try:
                os.remove(p)
            except Exception:
                pass


def _cartoonize_pil(src_jpg: str, dst_jpg: str) -> Optional[str]:
    """
    PIL-based cartoon/anime effect as fallback when ComfyUI is unavailable.
    Steps: posterize colors → boost saturation → smooth → edge overlay.
    """
    try:
        from PIL import Image, ImageFilter, ImageEnhance, ImageOps, ImageChops
        img = Image.open(src_jpg).convert("RGB")
        # Smooth to remove noise before posterization
        smooth = img.filter(ImageFilter.GaussianBlur(radius=1.5))
        # Posterize: reduce colors to cartoon-like palette
        poster = ImageOps.posterize(smooth, 4)
        # Boost saturation and contrast for vivid anime look
        poster = ImageEnhance.Color(poster).enhance(2.0)
        poster = ImageEnhance.Contrast(poster).enhance(1.3)
        # Extract and threshold edges
        edges = smooth.filter(ImageFilter.FIND_EDGES).convert("L")
        edges = edges.point(lambda x: 0 if x < 20 else min(255, x * 3))
        edges_inv = ImageOps.invert(edges).convert("RGB")
        # Multiply posterized image with inverted edges → dark outlines
        result = ImageChops.multiply(poster, edges_inv)
        result.save(dst_jpg, "JPEG", quality=90)
        return dst_jpg
    except Exception as e:
        logger.warning(f"PIL cartoonize failed: {e}")
        return None


async def _gen_transition_anime_frames(
    mp4: str, selected: List[Seg]
) -> List[Optional[str]]:
    """
    For each boundary between selected segments, extract the first frame of the
    NEXT segment and convert to anime style via ComfyUI.
    Returns list of length len(selected)-1 (None where generation failed).
    Caller must delete the returned temp files.
    """
    n = len(selected)
    if n < 2:
        return []
    comfy_ok = False
    try:
        from comfyui_client import anime_img2img, health_check
        comfy_ok = await health_check()
    except Exception:
        pass

    async def _one(seg: Seg, idx: int) -> Optional[str]:
        frame_tmp  = tempfile.mktemp(suffix=".jpg")   # 1080p source frame
        comfy_tmp  = tempfile.mktemp(suffix=".jpg")   # COMFY_W×COMFY_H for ComfyUI
        anime_tmp  = tempfile.mktemp(suffix=".jpg")   # final output
        try:
            pre = max(0.0, seg.start - 3.0)
            fine = seg.start - pre
            # Extract at 1080×1920 (half-4K): 2× better upscale to 4K vs 576×1024
            _FW, _FH = OUT_W // 2, OUT_H // 2   # 1080×1920
            cmd = [
                "ffmpeg", "-y",
                "-ss", f"{pre:.3f}", "-i", mp4,
                "-ss", f"{fine:.3f}", "-frames:v", "1",
                "-vf", (
                    f"scale={_FW}:{_FH}:force_original_aspect_ratio=decrease,"
                    f"pad={_FW}:{_FH}:(ow-iw)/2:(oh-ih)/2"
                ),
                "-q:v", "2", frame_tmp,
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )
            await proc.communicate()
            if proc.returncode != 0 or not os.path.exists(frame_tmp):
                return None

            if comfy_ok:
                # Downscale to ComfyUI-safe SD1.5 resolution before img2img
                try:
                    from PIL import Image as _PIL
                    _img = _PIL.open(frame_tmp).convert("RGB")
                    _img = _img.resize((COMFY_W, COMFY_H), _PIL.LANCZOS)
                    _img.save(comfy_tmp, "JPEG", quality=88)
                except Exception:
                    comfy_tmp = frame_tmp   # fallback: send 1080p directly

                seed = (hash(mp4) ^ idx * 0xCAFE) & 0xFFFFFF
                ok = await anime_img2img(comfy_tmp, anime_tmp, seed=seed, timeout=90)
                if ok and os.path.exists(anime_tmp) and os.path.getsize(anime_tmp) > 0:
                    return anime_tmp   # ComfyUI output (576×1024), upscaled by _merge_anime

            # PIL fallback: cartoonize at 1080×1920 (much sharper than 576×1024 when upscaled to 4K)
            return _cartoonize_pil(frame_tmp, anime_tmp)
        except Exception as e:
            logger.warning(f"Anime transition frame {idx} error: {e}")
            return None
        finally:
            for _p in {frame_tmp, comfy_tmp}:  # set deduplicates when comfy_tmp==frame_tmp
                try:
                    os.remove(_p)
                except Exception:
                    pass

    sem_frames = asyncio.Semaphore(1)  # M2 8GB: 串行帧提取，避免多路4K解码叠加内存

    async def _one_limited(seg: Seg, idx: int) -> Optional[str]:
        async with sem_frames:
            return await _one(seg, idx)

    tasks = [_one_limited(selected[i + 1], i) for i in range(n - 1)]
    results = list(await asyncio.gather(*tasks))
    ok_count = sum(1 for r in results if r)
    logger.info(f"Anime transition frames: {ok_count}/{n - 1} generated")
    return results


async def _gen_zoom_punch_clips(
    mp4: str, selected: List[Seg], boundaries: List[int]
) -> dict:
    """
    For each boundary, extract the first frame of the NEXT segment and apply a
    1.5× zoom-in crop targeting the face/wig area (upper-centre of frame).
    Returns {boundary_i: JPEG_path}. Caller must delete temp files.
    """
    async def _one(bi: int) -> tuple:
        seg = selected[bi + 1]
        out_tmp = tempfile.mktemp(suffix=".jpg")
        try:
            pre = max(0.0, seg.start - 3.0)
            fine = seg.start - pre
            cmd = [
                "ffmpeg", "-y",
                "-ss", f"{pre:.3f}", "-i", mp4,
                "-ss", f"{fine:.3f}", "-frames:v", "1",
                "-vf", (
                    # Step 1: scale source to 4K
                    f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease,"
                    f"pad={OUT_W}:{OUT_H}:(ow-iw)/2:(oh-ih)/2,"
                    # Step 2: crop upper-centre at 1/ZOOM_FACTOR size → 1.5× zoom toward face
                    f"crop={ZOOM_W}:{ZOOM_H}:{ZOOM_X}:{ZOOM_Y},"
                    # Step 3: scale cropped area back to 4K (high-quality)
                    f"scale={OUT_W}:{OUT_H}:flags=lanczos"
                ),
                "-q:v", "2", out_tmp,
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate()
            if proc.returncode == 0 and os.path.exists(out_tmp) and os.path.getsize(out_tmp) > 0:
                return bi, out_tmp
            return bi, None
        except Exception as e:
            logger.warning(f"Zoom punch frame error at boundary {bi}: {e}")
            try:
                os.remove(out_tmp)
            except Exception:
                pass
            return bi, None

    sem_zoom = asyncio.Semaphore(1)  # M2 8GB: 串行帧提取，避免多路2K解码叠加内存

    async def _one_sem(bi: int) -> tuple:
        async with sem_zoom:
            return await _one(bi)

    pairs = await asyncio.gather(*[_one_sem(bi) for bi in boundaries])
    result = {bi: path for bi, path in pairs if path}
    logger.info(f"Zoom punch clips: {len(result)}/{len(boundaries)} generated")
    return result


async def _gen_person_frames(
    mp4: str, selected: List[Seg], boundaries: List[int]
) -> dict:
    """
    For each boundary in `boundaries`, extract the last frame of segment[i] and
    apply rembg background removal to isolate the person.
    Returns dict {boundary_i: PNG_path}. Caller must delete temp files.
    """
    if not boundaries:
        return {}
    try:
        import rembg
    except ImportError:
        logger.debug("rembg not installed – person overlay transitions disabled")
        return {}

    async def _one(bi: int) -> tuple:
        seg = selected[bi]
        frame_tmp = tempfile.mktemp(suffix=".jpg")
        person_tmp = tempfile.mktemp(suffix=".png")
        try:
            seek = max(0.0, seg.end - 0.5)
            cmd = [
                "ffmpeg", "-y",
                "-ss", f"{seek:.3f}", "-i", mp4,
                "-frames:v", "1",
                "-vf", (
                    f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease,"
                    f"pad={OUT_W}:{OUT_H}:(ow-iw)/2:(oh-ih)/2"
                ),
                "-q:v", "2", frame_tmp,
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )
            await proc.communicate()
            if proc.returncode != 0 or not os.path.exists(frame_tmp):
                return bi, None

            # Try GPU rembg first (CUDA, <0.5s/frame); fallback to local CPU (~5-30s/frame)
            _used_gpu_rembg = False
            try:
                from gpu_state import is_online as _gpu_online
                if _gpu_online():
                    import aiohttp as _aiohttp_rembg
                    with open(frame_tmp, "rb") as _f:
                        _img_data = _f.read()
                    async with _aiohttp_rembg.ClientSession() as _sess:
                        _form = _aiohttp_rembg.FormData()
                        _form.add_field("file", _img_data, filename="frame.jpg", content_type="image/jpeg")
                        async with _sess.post(
                            f"{_GPU_SERVICE_URL}/rembg",
                            data=_form,
                            timeout=_aiohttp_rembg.ClientTimeout(total=30),
                        ) as _r:
                            if _r.status == 200:
                                _rembg_data = await _r.read()
                                with open(person_tmp, "wb") as _f:
                                    _f.write(_rembg_data)
                                _used_gpu_rembg = True
            except Exception:
                pass

            if not _used_gpu_rembg:
                def _remove_bg():
                    with open(frame_tmp, "rb") as f:
                        data = f.read()
                    result = rembg.remove(data)
                    with open(person_tmp, "wb") as f:
                        f.write(result)
                await asyncio.get_running_loop().run_in_executor(None, _remove_bg)
            if os.path.exists(person_tmp) and os.path.getsize(person_tmp) > 0:
                return bi, person_tmp
            return bi, None
        except Exception as e:
            logger.warning(f"Person frame error at boundary {bi}: {e}")
            try:
                os.remove(person_tmp)
            except Exception:
                pass
            return bi, None
        finally:
            try:
                os.remove(frame_tmp)
            except Exception:
                pass

    sem_rembg = asyncio.Semaphore(1)  # rembg loads U2Net model ~1-2 GB per inference; keep serial

    async def _one_rembg(bi: int) -> tuple:
        async with sem_rembg:
            return await _one(bi)

    results = await asyncio.gather(*[_one_rembg(bi) for bi in boundaries])
    out = {bi: path for bi, path in results if path}
    logger.info(f"Person overlay frames: {len(out)}/{len(boundaries)} generated")
    return out


# ── SRT parsing ───────────────────────────────────────────────────────────────

def _ts_to_sec(ts: str) -> float:
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
    return h * 3600 + m * 60 + s


def parse_srt(path: str) -> List[Seg]:
    with open(path, encoding="utf-8") as f:
        content = f.read()
    segs = []
    for block in re.split(r"\n{2,}", content.strip()):
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if len(lines) < 3:
            continue
        try:
            idx = int(lines[0])
            arrow = lines[1].split("-->")
            start = _ts_to_sec(arrow[0])
            end   = _ts_to_sec(arrow[1])
            text  = " ".join(lines[2:])
            segs.append(Seg(idx=idx, start=start, end=end, text=text))
        except (ValueError, IndexError):
            continue
    return segs


# ── Scoring ───────────────────────────────────────────────────────────────────

def _merge_short_segs(segs: List[Seg], min_dur: float = 3.0, max_gap: float = 1.5, max_merged: float = 6.0) -> List[Seg]:
    """Merge consecutive SRT segments that are too short into scene-level segments.

    Segments whose individual duration < min_dur are merged with their neighbours
    as long as the inter-segment gap is <= max_gap and the combined duration stays
    <= max_merged.  This handles fine-grained transcripts where each sentence is
    only 1-2 seconds long.
    """
    if not segs:
        return segs
    out: List[Seg] = []
    buf = Seg(idx=segs[0].idx, start=segs[0].start, end=segs[0].end, text=segs[0].text)
    for nxt in segs[1:]:
        gap = nxt.start - buf.end
        combined = nxt.end - buf.start
        if buf.duration < min_dur and gap <= max_gap and combined <= max_merged:
            buf.end  = nxt.end
            buf.text = buf.text + " " + nxt.text
        else:
            out.append(buf)
            buf = Seg(idx=nxt.idx, start=nxt.start, end=nxt.end, text=nxt.text)
    out.append(buf)
    return out


def score_and_tag(seg: Seg) -> None:
    text = seg.text

    # Remove check
    for pat in _REMOVE_PATTERNS:
        if re.search(pat, text):
            seg.valid = False
            seg.reject_reason = "remove_pattern"
            return

    # Too short to be useful (min 3s per scene)
    if seg.duration < 3.0:
        seg.valid = False
        seg.reject_reason = "too_short"
        return

    # Trim over-long segments — product/wearing/detail keywords allow up to 18s（完整介绍一款假发需要时间）
    # 普通内容 cap 10s
    has_product_kw = any(kw in text for kw in (_PRODUCT_KW | _DETAIL_KW | _WEARING_KW | _COMFORT_KW))
    max_dur = 18.0 if has_product_kw else 10.0
    if seg.duration > max_dur:
        seg.end = seg.start + max_dur

    # Keyword score — uses _SCORES_EFFECTIVE which incorporates human-approved rule overrides
    score = 0.0
    for kw, pts in _SCORES_EFFECTIVE.items():
        if kw in text:
            score += pts

    # Boost punchy short segments (3–4s sweet spot)
    if 3.0 <= seg.duration <= 4.0:
        score *= 1.2

    seg.score = round(score, 2)
    # 不因 score=0 丢弃片段——demo/佩戴/讲解内容同样有价值，低分段作为 fill 填入
    # （零分段最终排在高分段之后，靠 fill 逻辑填充时长预算）

    # Category tag — 10-category narrative system
    # Priority order mirrors narrative arc (higher CTR categories checked first)
    if any(kw in text for kw in _PROBLEM_KW):
        seg.category = "problem"
    elif any(kw in text for kw in _COMPARISON_KW):
        seg.category = "comparison"
    elif any(kw in text for kw in _SOCIAL_PROOF_KW):
        seg.category = "social_proof"
    elif any(kw in text for kw in _DETAIL_KW):
        seg.category = "detail"
    elif any(kw in text for kw in _WEARING_KW):
        seg.category = "wearing"
    elif any(kw in text for kw in _PRODUCT_KW):
        seg.category = "product"
    elif any(kw in text for kw in _COMFORT_KW):
        seg.category = "comfort"
    elif any(kw in text for kw in _RESULT_KW):
        seg.category = "result"
    elif any(kw in text for kw in _SCENE_KW):
        seg.category = "scene"
    elif any(kw in text for kw in _CONVERT_KW):
        seg.category = "convert"


# ── Silence detection ─────────────────────────────────────────────────────────

async def detect_silence(mp4: str, noise_db: int = -35, min_dur: float = 1.5) -> List[Tuple[float, float]]:
    cmd = [
        "ffmpeg", "-i", mp4,
        "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}",
        "-f", "null", "-",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    out = stderr.decode()
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", out)]
    ends   = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", out)]
    return list(zip(starts, ends))


def _silence_ratio(seg: Seg, silences: List[Tuple[float, float]]) -> float:
    if seg.duration <= 0:
        return 1.0
    overlap = sum(
        max(0.0, min(seg.end, se) - max(seg.start, ss))
        for ss, se in silences
    )
    return overlap / seg.duration


# ── Clip selection ─────────────────────────────────────────────────────────────

def _pick_by_category(segs: List[Seg], cat: str, budget: float) -> List[Seg]:
    pool = sorted(
        [s for s in segs if s.category == cat and s.score > 0],
        key=lambda s: s.score, reverse=True
    )
    chosen, used = [], 0.0
    for s in pool:
        if used + s.duration <= budget:
            chosen.append(s)
            used += s.duration
    return chosen


# ── Composite style presets ────────────────────────────────────────────────────
# Each preset = (motion, transition_type, transition_dur)
_STYLES: dict[str, tuple] = {
    # ── 抓注意 (attention-grabbing) ──
    "attention_r":  ("push_in_strong",  "fadewhite",      0.20),
    "attention_l":  ("zoom_pan_left",   "fadewhite",      0.20),
    "hook_shake":   ("shake",           "zoomin",         0.28),
    "diag_in":      ("push_in_strong",  "diagtl",         0.25),
    # ── 展示细节 (detail showcase) ──
    "detail_r":     ("zoom_pan_right",  "smoothleft",     0.40),
    "detail_l":     ("zoom_pan_left",   "smoothright",    0.40),
    "center_r":     ("zoom_pan_right",  "center_fade",    0.40),
    "radial_in":    ("push_in",         "radial",         0.35),
    # ── 种草 (seeding/pull-back) ──
    "seed":         ("pull_out",        "fadegrays",      0.40),
    "seed_tilt":    ("tilt_down",       "fadegrays",      0.40),
    "pixel_mix":    ("pull_out",        "pixel_dissolve", 0.40),
    # ── 叙事转折 (narrative pivot) ──
    "pivot":        ("rotate_ccw",      "fadeblack",      0.50),
    "pivot_push":   ("pull_out",        "fadeblack",      0.45),
    "shadow_push":  ("push_in",         "shadow_sweep",   0.35),
    # ── 社交证明 (social proof) ──
    "social_up":    ("tilt_up",         "wipeleft",       0.35),
    "social_down":  ("tilt_down",       "wipeleft",       0.35),
    "slide_in_r":   ("pan_right",       "slideleft",      0.30),
    "slide_in_l":   ("pan_left",        "slideright",     0.30),
    "squeeze_r":    ("tilt_up",         "squeezeh",       0.35),
    # ── 快切填充 (fast fill cuts) ──
    "quick_r":      ("pan_right",       "dissolve",       0.22),
    "quick_l":      ("pan_left",        "dissolve",       0.22),
    "quick_in":     ("push_in",         "hblur",          0.28),
    "quick_rot":    ("rotate_cw",       "dissolve",       0.25),
    "diag_wipe":    ("pan_right",       "diagonal_wipe",  0.28),
    # ── CTA 结尾 ──
    "cta":          ("pull_out",        "fadegrays",      0.40),
    # ── 特效转场 (overlay composites) ──
    "polaroid_tr":     ("push_in",  "polaroid",       0.40),
    "phone_zoom_tr":   ("push_in",  "phone_zoom",     0.40),
    "camera_out_tr":   ("pull_out", "camera_zoomout", 0.40),
}

# Style pools by narrative position — random selection within the pool
# 每个 pool 均加入 slide/zoom 类转场，增强视觉流动感
_STYLE_POOLS: dict[str, list] = {
    "hook":         ["hook_shake",  "attention_r",  "attention_l",  "diag_in",      "phone_zoom_tr"],
    "problem":      ["hook_shake",  "pivot",        "pivot_push",   "shadow_push",  "attention_r",   "slide_in_r"],
    "comparison":   ["attention_r", "attention_l",  "diag_in",      "hook_shake",   "polaroid_tr",   "phone_zoom_tr"],
    "social_proof": ["social_up",   "social_down",  "slide_in_r",   "slide_in_l",   "squeeze_r",     "phone_zoom_tr"],
    "product":      ["detail_r",    "detail_l",     "center_r",     "radial_in",    "seed",          "phone_zoom_tr", "slide_in_r"],
    "wearing":      ["detail_r",    "detail_l",     "radial_in",    "quick_in",     "center_r",      "phone_zoom_tr", "slide_in_l"],
    "detail":       ["radial_in",   "center_r",     "detail_r",     "quick_in",     "phone_zoom_tr"],
    "comfort":      ["seed",        "seed_tilt",    "pixel_mix",    "quick_l",      "slide_in_l",    "slide_in_r"],
    "result":       ["seed",        "seed_tilt",    "pixel_mix",    "center_r",     "camera_out_tr", "slide_in_r"],
    "scene":        ["slide_in_r",  "slide_in_l",   "social_up",    "social_down",  "phone_zoom_tr"],
    "convert":      ["cta",         "slide_in_r"],
    "solution":     ["detail_r",    "detail_l",     "center_r",     "radial_in",    "phone_zoom_tr"],
    "neutral":      ["quick_r",     "quick_l",      "quick_in",     "quick_rot",
                     "slide_in_r",  "slide_in_l",   "radial_in",    "diag_in",
                     "diag_wipe",   "detail_r",     "detail_l",     "phone_zoom_tr"],
}


def _assign_styles(assembled: List[Seg], seed: int = 0) -> None:
    """Assign motion + transition to every segment using composite style presets."""
    import random as _random
    rng = _random.Random(seed)

    # 细节特写关键词 → 强制 push_in_strong（对准发丝/发根区域推进放大）
    # 同时覆盖 detail 类段落的所有核心词
    _HAIR_DETAIL_KW = frozenset([
        "发丝", "发根", "发纹", "仿真皮", "仿递针", "仿头皮", "头皮",
        "发质", "头顶", "分缝", "发缝", "毛流", "毛鳞片",
        # _DETAIL_KW 同步（detail类段落一律 push_in_strong）
        "发缝真实", "发根清晰", "分缝自然", "发丝细腻",
        "贴合头皮", "边缘自然", "顺滑", "不打结", "不反光", "颜色自然",
        "特写", "近景", "细节", "发丝质感",
        # 额外细节词
        "仿真头皮", "仿生头皮", "递针工艺", "单根勾织", "仿生毛孔",
        "中分", "抠一抠", "往后", "往前", "拨一拨", "翻一翻",
        "扒开", "掀开", "扯开", "挑开",
        # 身体部位细节词 → 镜头放大对应区域
        "耳后", "耳朵", "耳边", "耳侧",
        "后脑勺", "后脑", "枕骨", "后颈",
        "鬓角", "鬓边", "两鬓",
        "侧面", "侧边", "从侧面", "侧边线",
        "发际线", "边缘", "轮廓",
        "颈部", "脖子", "颈后",
        "看这里", "看这边", "这个位置", "这里", "这边",
        "放大", "拉近", "近一点",
    ])

    def _pos(seg: Seg, idx: int) -> str:
        return "hook" if idx == 0 else seg.category

    for i, seg in enumerate(assembled):
        pool_key = _pos(seg, i)
        pool = _STYLE_POOLS.get(pool_key, _STYLE_POOLS["neutral"])
        seg_seed = seed + i * 31 + (hash(seg.text[:16]) & 0xFFFF)
        rng.seed(seg_seed)
        style_name = rng.choice(pool)
        motion, t_type, t_dur = _STYLES[style_name]
        if any(kw in seg.text for kw in _HAIR_DETAIL_KW) or seg.category == "detail":
            motion = "push_in_strong"
        seg.motion = motion
        if i > 0:
            seg.transition = f"{t_type}:{t_dur:.2f}"

    MIN_MOTION_SEGS = 4
    motion_count = sum(1 for s in assembled if s.motion != "static")
    if motion_count < MIN_MOTION_SEGS:
        static_segs = sorted(
            [s for s in assembled if s.motion == "static"],
            key=lambda s: getattr(s, "score", 0)
        )
        replacements = ["push_in", "pull_out"]
        for idx_r, seg in enumerate(static_segs):
            if motion_count >= MIN_MOTION_SEGS:
                break
            seg.motion = replacements[idx_r % 2]
            motion_count += 1


def _select_from_valid(valid: List[Seg], clip_min: float = CLIP_MIN, clip_max: float = CLIP_MAX) -> List[Seg]:
    """10-step narrative arc for 假发 short-form video (巨量千川优质短视频结构).

    Assembly order (skips slots with no matching content):
      1. 痛点开头   problem      — viewer self-identifies with the problem
      2. 对比强化   comparison   — before state / contrast to amplify urgency
      3. 情绪刺激   social_proof — "同事以为我去烫头了" — social validation hook
      4. 产品展示   product      — core features / visual transformation
      5. 佩戴过程   wearing      — step-by-step demo; builds confidence
      6. 细节特写   detail       — close-up of hair quality; purchase trigger
      7. 舒适稳固   comfort      — addresses heat/stability doubts
      8. 戴后效果   result       — after-wearing visual impression
      9. 场景代入   scene        — specific use case (约会/通勤/婚礼 etc.)
     10. 转化收口   convert      — CTA forced last; shortest available
    """
    if not valid:
        return []

    # Hard requirement: total valid material must be >= CLIP_MIN (30s).
    # If there isn't enough content, return empty so the caller can reject the clip
    # rather than produce an under-length video.
    total_valid_dur = sum(s.duration for s in valid)
    if total_valid_dur < CLIP_MIN:
        logger.warning(
            f"Valid material ({total_valid_dur:.1f}s) < hard minimum {CLIP_MIN:.0f}s — "
            f"refusing to produce under-length clip"
        )
        return []
    # If valid material is between CLIP_MIN and clip_min, use all of it
    if total_valid_dur <= clip_min:
        logger.info(
            f"Valid material ({total_valid_dur:.1f}s) shorter than clip_min ({clip_min:.1f}s) — "
            f"returning all valid segments (still >= {CLIP_MIN:.0f}s hard floor)"
        )
        _assign_styles(valid, seed=0)
        return sorted(valid, key=lambda s: s.start)

    used_ids: set = set()

    def _pick_block(cat: str, budget: float, max_segs: int = 2) -> List[Seg]:
        pool = sorted(
            [s for s in valid if id(s) not in used_ids and s.category == cat and s.score > 0],
            key=lambda s: s.score, reverse=True,
        )
        chosen, used = [], 0.0
        for s in pool:
            if len(chosen) >= max_segs:
                break
            # 允许最后一个片段轻微超出budget（最多超2s），避免话说到一半被截断
            if used > 0 and used + s.duration > budget + 2.0:
                continue
            chosen.append(s)
            used += s.duration
        # 按时序重排，保持叙事连贯
        return sorted(chosen, key=lambda s: s.start)

    # ── Narrative slots (category, budget_s, max_segs) ───────────────────────
    # 每类预算足够大，保证一款假发产品的完整介绍不被截断
    _NARRATIVE_SLOTS = [
        ("problem",      15.0, 4),
        ("comparison",    8.0, 2),
        ("social_proof", 10.0, 3),
        ("product",      20.0, 6),   # 产品介绍最关键，给足预算
        ("wearing",      20.0, 6),   # 佩戴过程同等重要
        ("detail",       12.0, 4),
        ("comfort",      12.0, 4),
        ("result",        8.0, 2),
        ("scene",         8.0, 2),
        # "convert" handled separately as forced-last
    ]

    structured: List[Seg] = []
    for cat, budget, max_segs in _NARRATIVE_SLOTS:
        block = _pick_block(cat, budget, max_segs)
        structured.extend(block)
        used_ids.update(id(s) for s in block)

    # 按时间顺序排列 structured，避免跨时间点拼接导致内容跳跃
    structured = sorted(structured, key=lambda s: s.start)

    # ── Convert: forced last, always a convert segment ───────────────────────
    # Prefer unused convert segment; if none, reuse any convert segment;
    # only fall back to non-convert if no convert segments exist at all.
    convert_unused = sorted(
        [s for s in valid if id(s) not in used_ids and s.category == "convert"],
        key=lambda s: s.duration,
    )
    convert_any = sorted(
        [s for s in valid if s.category == "convert"],
        key=lambda s: s.duration,
    )
    if convert_unused:
        closer = [convert_unused[0]]
    elif convert_any:
        closer = [convert_any[0]]
    else:
        fallback = sorted(
            [s for s in valid if id(s) not in used_ids],
            key=lambda s: s.score, reverse=True,
        )
        closer = [fallback[0]] if fallback else []
    used_ids.update(id(s) for s in closer)

    # ── Fill remaining budget with unused segments ────────────────────────────
    used_dur = sum(s.duration for s in structured) + sum(s.duration for s in closer)
    # fill_budget must be at least enough to reach clip_min
    fill_budget = max(clip_max - used_dur, clip_min - used_dur)
    fill: List[Seg] = []
    if fill_budget > 0:
        fill_pool = sorted(
            [s for s in valid if id(s) not in used_ids],
            key=lambda s: s.score, reverse=True,
        )
        used = 0.0
        for s in fill_pool:
            if used >= fill_budget + 2.0:
                break
            # Don't skip segments that are needed to reach clip_min
            needed = max(0.0, clip_min - used_dur - used)
            if needed <= 0 and used + s.duration > fill_budget + 2.0:
                continue
            fill.append(s)
            used += s.duration
    fill = sorted(fill, key=lambda s: s.start)

    # 将 structured + fill 合并后按时间顺序排列，closer 强制置尾
    # 保持时序连贯性，减少前后内容跳跃感
    body = sorted(structured + fill, key=lambda s: s.start)
    assembled = body + closer

    # ── Pad to clip_min ───────────────────────────────────────────────────────
    total = sum(s.duration for s in assembled)
    if total < clip_min:
        all_used = {id(s) for s in assembled}
        extras = sorted(
            [s for s in valid if id(s) not in all_used],
            key=lambda s: s.score, reverse=True,
        )
        extra_added = []
        for s in extras:
            if total >= clip_min:  # stop once we've reached clip_min (not clip_max)
                break
            extra_added.append(s)
            total += s.duration
        # 把补充片段合入 body 并按时序重排
        body_new = sorted(body + extra_added, key=lambda s: s.start)
        assembled = body_new + closer

    # ── Cap segment count ─────────────────────────────────────────────────────
    if len(assembled) > MAX_CLIP_SEGMENTS:
        # 超限时，按得分保留最优片段（closer 固定保留）
        body_segs = assembled[:-len(closer)] if closer else assembled
        body_trimmed = sorted(
            sorted(body_segs, key=lambda s: s.score, reverse=True)[:MAX_CLIP_SEGMENTS - len(closer)],
            key=lambda s: s.start,
        )
        assembled = body_trimmed + closer
        # After cap, re-check clip_min: restore any dropped segments if needed
        capped_dur = sum(s.duration for s in assembled)
        if capped_dur < clip_min:
            dropped = [s for s in body_segs if id(s) not in {id(x) for x in assembled}]
            dropped_sorted = sorted(dropped, key=lambda s: s.score, reverse=True)
            restore = []
            for s in dropped_sorted:
                if capped_dur >= clip_min:
                    break
                restore.append(s)
                capped_dur += s.duration
            body_final = sorted([s for s in assembled if s not in (closer if closer else [])] + restore, key=lambda s: s.start)
            assembled = body_final + closer

    # ── Assign camera motion + transitions ────────────────────────────────────
    _seed = hash(assembled[0].text[:16]) & 0xFFFF if assembled else 0
    _assign_styles(assembled, seed=_seed)

    return assembled


def _expand_to_meet_minimum(
    segs: List[Seg],
    valid: List[Seg],
    clip_min: float = CLIP_MIN,
) -> List[Seg]:
    """Progressively relax rejection filters until total duration >= clip_min.

    Relaxation tiers (applied in order, stop when enough material is found):
      Tier 1 — add segments rejected only for being too short (<3 s) or high
               silence ratio; they are structurally intact and safe to include.
      Tier 2 — add zero-score / negative-score segments (no keyword match,
               or mildly penalised by avoid_kw); neutral content.
      Tier 3 — allow ALL non-remove_pattern segments (silent, short, low-score).

    Segments with reject_reason='remove_pattern' (链接/下播/催单硬广) are NEVER
    included regardless of tier.
    """
    cur_dur = sum(s.duration for s in valid)
    if cur_dur >= clip_min:
        return valid  # already enough, nothing to do

    valid_ids = {id(s) for s in valid}

    # Build candidate pools per tier (excluding already-valid and remove_pattern)
    tier1 = [
        s for s in segs
        if id(s) not in valid_ids
        and s.reject_reason != "remove_pattern"
        and s.reject_reason in ("too_short", "silence")
        and s.duration >= 1.0   # ignore sub-second flickers
    ]
    tier2 = [
        s for s in segs
        if id(s) not in valid_ids
        and s.reject_reason != "remove_pattern"
        and s.reject_reason not in ("too_short", "silence")
        and not s.valid          # any other invalidity (score<0, etc.)
    ]
    # Tier 3: everything that isn't remove_pattern and not already in pool
    all_ids = valid_ids | {id(s) for s in tier1} | {id(s) for s in tier2}
    tier3 = [
        s for s in segs
        if id(s) not in all_ids
        and s.reject_reason != "remove_pattern"
    ]

    expanded = list(valid)
    for tier_label, pool in [(1, tier1), (2, tier2), (3, tier3)]:
        if cur_dur >= clip_min:
            break
        # Sort by time position so added segments read chronologically
        pool_sorted = sorted(pool, key=lambda s: s.start)
        for s in pool_sorted:
            if cur_dur >= clip_min:
                break
            expanded.append(s)
            cur_dur += s.duration
        if cur_dur >= clip_min:
            logger.info(
                f"Padding: reached {cur_dur:.1f}s >= {clip_min:.0f}s after relaxing tier {tier_label}"
            )

    if cur_dur < clip_min:
        logger.warning(
            f"Padding exhausted all tiers: only {cur_dur:.1f}s available "
            f"(hard minimum {clip_min:.0f}s — clip will be rejected)"
        )

    return expanded


def select_clips(segs: List[Seg], clip_min: float = CLIP_MIN, clip_max: float = CLIP_MAX) -> List[Seg]:
    valid = [s for s in segs if s.valid]
    # If strict-valid pool is insufficient, progressively relax filters
    if sum(s.duration for s in valid) < CLIP_MIN:
        valid = _expand_to_meet_minimum(segs, valid, clip_min)
    return _select_from_valid(valid, clip_min, clip_max)


def select_clips_variant(
    segs: List[Seg],
    exclude_ids: set,
    clip_min: float = CLIP_MIN,
    clip_max: float = CLIP_MAX,
    seed: int = 0,
) -> List[Seg]:
    """Like select_clips but excludes segments already used in a prior variant."""
    valid = [s for s in segs if s.valid and id(s) not in exclude_ids]
    # If remaining content is insufficient, allow reuse but shuffle to differ from variant 0
    if sum(s.duration for s in valid) < clip_min:
        rng = random.Random(seed)
        valid = [s for s in segs if s.valid]
        rng.shuffle(valid)
    if sum(s.duration for s in valid) < CLIP_MIN:
        valid = _expand_to_meet_minimum(segs, valid, clip_min)
    return _select_from_valid(valid, clip_min, clip_max)


# ── Feedback-guided scoring ───────────────────────────────────────────────────

async def _feedback_to_hints(srt_path: str, feedback: str) -> dict:
    """
    Call Claude via Bedrock to convert user feedback into scoring hints.
    Returns a dict with keys: preferred_ranges, avoid_ranges, boost_keywords,
    avoid_keywords, prefer_longer, clip_min_override, clip_max_override.
    Falls back to empty hints on any error.
    """
    from analyzer import BEDROCK_URL, BEDROCK_MODEL, BEDROCK_TOKEN
    import httpx, json as _json, re as _re

    if not BEDROCK_TOKEN:
        logger.warning("Bedrock not configured, skipping feedback hints")
        return {}

    # Read SRT text (up to 6000 chars)
    try:
        with open(srt_path, encoding="utf-8") as f:
            raw_srt = f.read()
        lines = [l for l in raw_srt.splitlines()
                 if l.strip() and not l.strip().isdigit() and "-->" not in l]
        srt_text = "\n".join(lines)[:6000]
    except Exception:
        srt_text = ""

    prompt = f"""你是短视频剪辑专家。用户对当前剪辑效果不满意，请根据反馈和字幕内容给出改善建议。

用户反馈：
{feedback}

字幕片段（含时间轴，格式 秒数|内容）：
{srt_text}

请以JSON格式返回（只返回JSON，不含任何其他文字）：
{{
  "preferred_ranges": [[开始秒, 结束秒], ...],
  "avoid_ranges": [[开始秒, 结束秒], ...],
  "boost_keywords": ["词1", "词2"],
  "avoid_keywords": ["词1"],
  "prefer_longer": true或false,
  "clip_min_override": null或秒数,
  "clip_max_override": null或秒数,
  "reasoning": "一句话解释"
}}"""

    payload = {
        "messages": [{"role": "user", "content": [{"text": prompt}]}],
        "inferenceConfig": {"maxTokens": 600, "temperature": 0},
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{BEDROCK_URL}/model/{BEDROCK_MODEL}/converse",
                json=payload,
                headers={"Authorization": f"Bearer {BEDROCK_TOKEN}",
                         "Content-Type": "application/json"},
            )
        if resp.status_code != 200:
            logger.warning(f"Bedrock feedback hints error {resp.status_code}")
            return {}
        raw = resp.json()["output"]["message"]["content"][0]["text"]
        m = _re.search(r"\{.*\}", raw, _re.DOTALL)
        if m:
            hints = _json.loads(m.group())
            logger.info(f"Feedback hints: {hints.get('reasoning', '')}")
            return hints
    except Exception as e:
        logger.warning(f"Feedback hints failed: {e}")
    return {}


def _apply_hints(segs: List[Seg], hints: dict) -> None:
    """Apply Claude-generated hints to segment scores in-place."""
    if not hints:
        return

    boost_kw = hints.get("boost_keywords") or []
    avoid_kw = hints.get("avoid_keywords") or []
    preferred = hints.get("preferred_ranges") or []
    avoided   = hints.get("avoid_ranges") or []

    for seg in segs:
        if not seg.valid:
            continue
        # Keyword boosts / penalties
        for kw in boost_kw:
            if kw in seg.text:
                seg.score += 3.0
        for kw in avoid_kw:
            if kw in seg.text:
                seg.score -= 5.0
                if seg.score < 0:
                    seg.valid = False
                    seg.reject_reason = seg.reject_reason or "low_score"
        # Time-range preferences
        mid = (seg.start + seg.end) / 2
        for s, e in preferred:
            if s <= mid <= e:
                seg.score += 4.0
        for s, e in avoided:
            if s <= mid <= e:
                seg.valid = False
                seg.reject_reason = seg.reject_reason or "avoided_range"


# ── GPU offload path ──────────────────────────────────────────────────────────

_GPU_SERVICE_URL  = os.environ.get("GPU_SERVICE_URL",  "http://10.190.0.203:8877")
_GPU_WAIT_TIMEOUT = float(os.environ.get("GPU_WAIT_TIMEOUT", "600"))  # seconds to wait for GPU before local fallback

# Maps local clip output path → GPU clip job_id; populated by _gpu_clip_variant
# Used by transcribe.py to persist job_ids in DB for later GPU-side concat
_clip_job_id_cache: dict[str, str] = {}


async def _edit_via_gpu(
    mp4_filename: str,
    room_id: int,
    selected: List["Seg"],
    segs: List["Seg"],
    out_path: str,
    on_progress=None,
    mp4_path: Optional[str] = None,   # local path; enables auto-upload on 404
) -> Optional[str]:
    """
    Offload clip encoding to GPU server via NVENC.
    If the GPU returns 404 (file not found) and mp4_path is provided, the file is
    uploaded automatically and the job is retried.
    Returns out_path on success, None on failure.
    """
    ass_content = build_ass(selected, segs)
    best_seg = max(selected, key=lambda s: s.score) if any(s.score > 0 for s in selected) \
               else selected[max(0, len(selected) // 4)]

    def _seg_tr(seg: "Seg") -> str:
        """Extract xfade transition name from seg.transition ('type:dur' or plain name)."""
        if not seg.transition:
            return "dissolve"
        raw = seg.transition.split(":")[0]
        return _TR_REMAP.get(raw, raw) if raw in _TR_REMAP else raw

    payload = {
        "mp4_filename": mp4_filename,
        "room_id": room_id,
        "segments": [
            {
                "start": s.start,
                "end": s.end,
                "transition": _seg_tr(s),
                "transition_duration": float(s.transition.split(":")[1]) if s.transition and ":" in s.transition else 0.35,
            }
            for s in selected
        ],
        "ass_content": ass_content,
        "thumb_seek": best_seg.start + 1.0,
    }

    import aiohttp as _aiohttp

    async def _submit_aio() -> Optional[str]:
        """POST /clip-jobs via aiohttp; returns job_id or None."""
        nonlocal mp4_path
        try:
            async with _aiohttp.ClientSession() as session:
                async with session.post(
                    f"{_GPU_SERVICE_URL}/clip-jobs",
                    json=payload,
                    timeout=_aiohttp.ClientTimeout(total=30),
                ) as resp:
                    status_code = resp.status
                    resp_text = await resp.text()
        except Exception as e:
            logger.warning(f"GPU clip job submission failed: {e}")
            return None
        if status_code == 404 and mp4_path and os.path.exists(mp4_path):
            # File not on GPU server — upload it, then retry once
            logger.info(f"GPU 404: auto-uploading {mp4_filename} to GPU server then retrying...")
            try:
                from sync import sync_file
                await sync_file(mp4_path, room_id)
            except Exception as ue:
                logger.warning(f"Auto-upload for {mp4_filename} failed: {ue}")
                return None
            try:
                async with _aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{_GPU_SERVICE_URL}/clip-jobs",
                        json=payload,
                        timeout=_aiohttp.ClientTimeout(total=30),
                    ) as resp:
                        status_code = resp.status
                        resp_text = await resp.text()
            except Exception as e:
                logger.warning(f"GPU clip job retry after upload failed: {e}")
                return None
        if status_code != 201:
            logger.warning(f"GPU clip job rejected: {status_code} {resp_text[:200]}")
            return None
        import json as _json
        jid = _json.loads(resp_text)["job_id"]
        logger.info(f"GPU clip job created: {jid} for {mp4_filename}")
        return jid

    job_id = await _submit_aio()
    if not job_id:
        return None

    # Poll until done or 25-minute timeout; recover if GPU goes offline mid-job
    deadline = time.time() + 1500
    consecutive_errors = 0
    while time.time() < deadline:
        await asyncio.sleep(5.0)
        try:
            async with _aiohttp.ClientSession() as session:
                async with session.get(
                    f"{_GPU_SERVICE_URL}/clip-jobs/{job_id}",
                    timeout=_aiohttp.ClientTimeout(total=15),
                ) as resp:
                    data = await resp.json()
            consecutive_errors = 0
        except Exception:
            consecutive_errors += 1
            if consecutive_errors >= 6:   # ~30s of consecutive failures
                from gpu_state import is_online as _gpu_is_online, wait_until_online as _gpu_wait
                if not _gpu_is_online():
                    logger.info(f"GPU offline during clip job {job_id} — waiting for recovery...")
                    try:
                        await asyncio.wait_for(_gpu_wait(), timeout=600)
                    except asyncio.TimeoutError:
                        logger.warning(f"GPU stayed offline; abandoning clip job {job_id}")
                        return None
                    # GPU is back — check if job still exists
                    consecutive_errors = 0
                    try:
                        async with _aiohttp.ClientSession() as session:
                            async with session.get(
                                f"{_GPU_SERVICE_URL}/clip-jobs/{job_id}",
                                timeout=_aiohttp.ClientTimeout(total=15),
                            ) as r:
                                if r.status == 404:
                                    # Job was lost in restart — resubmit
                                    logger.info(f"Clip job {job_id} lost after GPU restart, resubmitting...")
                                    new_jid = await _submit_aio()
                                    if new_jid:
                                        job_id = new_jid
                                    else:
                                        return None
                    except Exception:
                        pass
            continue

        status = data.get("status")
        pct    = data.get("pct", 0)
        phase  = data.get("phase", "")

        if on_progress and pct > 0:
            if phase == "preprocess":
                await on_progress("preprocess", pct, 40)
            elif phase == "merge":
                await on_progress("merge", pct - 40, 35)
            elif phase in ("final", "thumbnail", "done"):
                await on_progress("final", 1, 1)

        if status == "done":
            break
        if status == "error":
            logger.warning(f"GPU clip job {job_id} error: {data.get('error')}")
            return None
    else:
        logger.warning(f"GPU clip job {job_id} timed out")
        return None

    # Download result
    try:
        async with _aiohttp.ClientSession() as session:
            async with session.get(
                f"{_GPU_SERVICE_URL}/clip-jobs/{job_id}/mp4",
                timeout=_aiohttp.ClientTimeout(total=300),
            ) as r:
                if r.status != 200:
                    logger.warning(f"GPU clip download failed: {r.status}")
                    return None
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                content = await r.read()
        with open(out_path, "wb") as f:
            f.write(content)
    except Exception as e:
        logger.warning(f"GPU clip download error: {e}")
        return None

    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        logger.warning("GPU clip download produced empty file")
        return None

    size_mb = os.path.getsize(out_path) / 1024 / 1024
    logger.info(f"GPU clip downloaded: {out_path} ({size_mb:.1f} MB)")
    _clip_job_id_cache[out_path] = job_id  # store for GPU-side concat later
    return out_path


# ── Fast local fallback (stream-copy + single encode) ─────────────────────────

async def _fast_local_clip(
    mp4: str,
    selected: List[Seg],
    segs: List[Seg],
    out: str,
    on_progress=None,
) -> bool:
    """
    Fast local fallback when GPU is unavailable.
    Stream-copy segment extraction + concat + single re-encode pass.
    Skips all transitions and pre-processing.  ~10-30s vs 30+ minutes.
    """
    ass_content = build_ass(selected, segs)
    has_subs = "Dialogue:" in ass_content

    with tempfile.TemporaryDirectory() as tmp:
        ass_path = os.path.join(tmp, "subs.ass")
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)

        # Step 1: extract each segment via stream copy (no re-encode)
        seg_files: List[str] = []
        for i, seg in enumerate(selected):
            seg_out = os.path.join(tmp, f"seg_{i:03d}.mp4")
            pad_start = min(SEG_PAD, seg.start)
            t_start = seg.start - pad_start
            t_dur = seg.duration + pad_start + SEG_PAD
            cmd = [
                "ffmpeg", "-y",
                "-ss", f"{t_start:.3f}",
                "-t", f"{t_dur:.3f}",
                "-i", mp4,
                "-c", "copy",
                "-reset_timestamps", "1",
                "-avoid_negative_ts", "make_zero",
                seg_out,
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
            )
            await proc.communicate()
            if proc.returncode == 0 and os.path.exists(seg_out) and os.path.getsize(seg_out) > 0:
                seg_files.append(seg_out)
            else:
                logger.warning(f"_fast_local_clip: segment {i} extract failed")
                return False

        # Step 2: concat all segments (stream copy)
        list_path = os.path.join(tmp, "concat.txt")
        with open(list_path, "w") as lf:
            for sf in seg_files:
                lf.write(f"file '{sf}'\n")
        merged = os.path.join(tmp, "merged.mp4")
        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", merged]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        await proc.communicate()
        if proc.returncode != 0 or not os.path.exists(merged) or os.path.getsize(merged) == 0:
            logger.error("_fast_local_clip: concat failed")
            return False

        # Step 3: single re-encode pass — scale to 1080×1920 + subtitles + music
        music_path = _pick_music()
        cmd = ["ffmpeg", "-y", "-i", merged]
        filter_parts: List[str] = []
        audio_map = "0:a"

        if music_path:
            cmd += ["-stream_loop", "-1", "-i", music_path]
            filter_parts.append(
                "[0:a]acompressor=threshold=-25dB:ratio=3:attack=5:release=100:makeup=4dB,"
                "loudnorm=I=-16:TP=-1.5:LRA=11,"
                "aformat=channel_layouts=stereo[voice];"
                "[1:a]volume=0.40,aformat=channel_layouts=stereo[bgm];"
                "[voice][bgm]amix=inputs=2:duration=first:normalize=0[aout]"
            )
            audio_map = "[aout]"
        else:
            filter_parts.append(
                "[0:a]acompressor=threshold=-25dB:ratio=3:attack=5:release=100:makeup=4dB,"
                "loudnorm=I=-16:TP=-1.5:LRA=11,"
                "aformat=channel_layouts=stereo[aout]"
            )
            audio_map = "[aout]"

        vf = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2"
        if has_subs:
            escaped = ass_path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
            vf += f",ass={escaped}"
        filter_parts.append(f"[0:v]{vf}[vout]")

        cmd += ["-filter_complex", ";".join(filter_parts)]
        cmd += [
            "-map", "[vout]", "-map", audio_map,
            "-pix_fmt", "yuv420p",
            "-c:v", "h264_videotoolbox", "-b:v", "10M", "-allow_sw", "1",
            "-ar", "44100", "-ac", "2",
            "-c:a", "aac", "-b:a", "192k",
            out,
        ]
        if on_progress:
            await on_progress("final", 0, 1)
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        ok = proc.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0
        if not ok:
            logger.error(
                f"_fast_local_clip final encode failed rc={proc.returncode}: "
                f"{stderr.decode(errors='replace')[-1000:]}"
            )
        return ok


# ── Main entry ────────────────────────────────────────────────────────────────

async def edit_recording(mp4_path: str, srt_path: str, room_name: str = "unknown", record_date: str = "", clip_duration: Optional[float] = None, on_progress=None, feedback: Optional[str] = None, room_id: Optional[int] = None, clip_engine: str = "legacy") -> Optional[str]:
    """
    Produce a highlight clip from a recording + its SRT.
    clip_engine='legacy' uses keyword-based 10-step narrative selection.
    clip_engine='v2'     uses hairstyle-boundary detection — picks the best single wig intro window.
    Returns local path to the output _clip.mp4, or None on failure.
    """
    if not os.path.exists(mp4_path):
        logger.error(f"MP4 not found: {mp4_path}")
        return None
    if not os.path.exists(srt_path):
        logger.error(f"SRT not found: {srt_path}")
        return None

    # Parse + merge short segments + score
    segs = parse_srt(srt_path)
    if not segs:
        logger.warning(f"Empty SRT: {srt_path}")
        return None
    segs = _merge_short_segs(segs)
    for seg in segs:
        score_and_tag(seg)

    # Detect silence and penalize silent segments
    try:
        silences = await detect_silence(mp4_path)
        for seg in segs:
            if seg.valid and _silence_ratio(seg, silences) > 0.6:
                seg.valid = False
                seg.reject_reason = "silence"
                logger.debug(f"Silence removed: [{seg.start:.1f}-{seg.end:.1f}] {seg.text[:30]}")
    except Exception as e:
        logger.warning(f"Silence detection skipped: {e}")

    # Phase B: Audio energy scoring
    try:
        from segment_scorer import enrich_audio_scores
        await enrich_audio_scores(mp4_path, segs)
    except Exception as e:
        logger.warning(f"Audio scoring skipped: {e}")

    # Phase C: Visual quality scoring (OpenCV sharpness + face detection)
    try:
        from segment_scorer import enrich_visual_scores
        await enrich_visual_scores(mp4_path, segs)
    except Exception as e:
        logger.warning(f"Visual scoring skipped: {e}")

    # Phase D: Claude Haiku visual semantic scoring (wig visibility + demo quality)
    try:
        from segment_scorer import enrich_semantic_scores
        await enrich_semantic_scores(mp4_path, segs)
    except Exception as e:
        logger.warning(f"Semantic scoring skipped: {e}")

    # Phase 2: LLM text scoring — rescues zero-score segments with narrative value,
    # and generates rule_suggestions when LLM disagrees with keyword scores
    try:
        from segment_scorer import enrich_llm_text_scores
        await enrich_llm_text_scores(segs, recording_id=room_id)
    except Exception as e:
        logger.warning(f"LLM text scoring skipped: {e}")

    # v2: 发型边界识别，仅在识别到的发型窗口内选段
    if clip_engine == "v2":
        try:
            from wig_boundary import detect_boundaries, pick_best_window
            boundaries = await detect_boundaries(srt_path)
            window = pick_best_window(boundaries)
            if window:
                logger.info(
                    f"[v2] Wig window: {window['wig']} "
                    f"({window['start_sec']:.0f}s–{window['end_sec']:.0f}s, "
                    f"complete={window['complete']})"
                )
                segs = [s for s in segs if s.start >= window["start_sec"] and s.end <= window["end_sec"]]
                if not segs:
                    logger.warning("[v2] No segments in wig window, falling back to all segs")
            else:
                logger.warning("[v2] No wig boundaries detected, using full recording")
        except Exception as e:
            logger.warning(f"[v2] Boundary detection error: {e}, continuing with all segs")

    # Apply feedback hints if provided
    if feedback:
        hints = await _feedback_to_hints(srt_path, feedback)
        _apply_hints(segs, hints)
        c_min = hints.get("clip_min_override") or ((clip_duration * 0.85) if clip_duration else (CLIP_MIN_V2 if clip_engine == "v2" else CLIP_MIN))
        c_max = hints.get("clip_max_override") or (clip_duration if clip_duration else (CLIP_MAX_V2 if clip_engine == "v2" else CLIP_MAX))
        if hints.get("prefer_longer"):
            c_min = max(c_min, CLIP_MIN * 1.3)
    else:
        if clip_engine == "v2":
            c_min = clip_duration * 0.85 if clip_duration else CLIP_MIN_V2
            c_max = clip_duration if clip_duration else CLIP_MAX_V2
        else:
            c_min = (clip_duration * 0.85) if clip_duration else CLIP_MIN
            c_max = clip_duration if clip_duration else CLIP_MAX

    # Enforce hard floor: never select below CLIP_MIN regardless of clip_duration
    c_min = max(c_min, CLIP_MIN)
    c_max = max(c_max, c_min)

    # Select clips
    selected = select_clips(segs, clip_min=c_min, clip_max=c_max)
    if not selected:
        logger.warning(f"No valid clips selected for {mp4_path}")
        return None

    total_dur = sum(s.duration for s in selected)
    logger.info(
        f"[{clip_engine}] Selected {len(selected)} segments, {total_dur:.1f}s "
        f"[{', '.join(s.category for s in selected)}]"
    )

    # Hard output duration gate: reject clips shorter than CLIP_MIN
    if total_dur < CLIP_MIN:
        logger.warning(
            f"[{clip_engine}] Selected duration {total_dur:.1f}s < hard minimum {CLIP_MIN:.0f}s — "
            f"refusing to encode under-length clip for {os.path.basename(mp4_path)}"
        )
        return None

    from datetime import datetime
    date_str  = record_date or datetime.utcnow().strftime("%Y%m%d")
    safe_name = re.sub(r'[\\/:*?"<>|]', '_', room_name)
    out_dir   = os.path.join(RECORDINGS_DIR, safe_name, date_str)
    os.makedirs(out_dir, exist_ok=True)
    seq       = len([f for f in os.listdir(out_dir) if f.endswith("_clip.mp4")]) + 1
    out_path  = os.path.join(out_dir, f"{safe_name}_{date_str}_{seq:03d}_clip.mp4")

    # ── Try GPU path first ────────────────────────────────────────────────────
    if room_id is not None:
        # Wait for GPU to come back online before attempting (up to _GPU_WAIT_TIMEOUT)
        from gpu_state import is_online as _gpu_is_online, wait_until_online as _gpu_wait
        if not _gpu_is_online():
            logger.info(f"GPU offline — waiting up to {_GPU_WAIT_TIMEOUT:.0f}s before clip job...")
            try:
                await asyncio.wait_for(_gpu_wait(), timeout=_GPU_WAIT_TIMEOUT)
                logger.info("GPU back online, proceeding with GPU clip")
            except asyncio.TimeoutError:
                logger.warning(f"GPU still offline after {_GPU_WAIT_TIMEOUT:.0f}s — using local fallback")
                room_id = None   # skip GPU attempt
        if room_id is not None:
            try:
                mp4_filename = os.path.basename(mp4_path)
                gpu_result = await _edit_via_gpu(
                    mp4_filename, room_id, selected, segs, out_path, on_progress,
                    mp4_path=mp4_path,
                )
                if gpu_result:
                    # GPU succeeded — generate thumbnail locally from original mp4
                    try:
                        if on_progress:
                            await on_progress("thumbnail", 0, 1)
                        from thumbnail import generate_thumbnail
                        best_seg = max(selected, key=lambda s: s.score) if any(s.score > 0 for s in selected) \
                                   else selected[max(0, len(selected) // 4)]
                        thumb = await generate_thumbnail(mp4_path, offset=best_seg.start + 1.0)
                        if thumb:
                            await _prepend_thumbnail(out_path, thumb)
                    except Exception as e:
                        logger.warning(f"Thumbnail prepend skipped (GPU path): {e}")
                    size_mb = os.path.getsize(out_path) / 1024 / 1024
                    logger.info(f"Clip ready (GPU): {out_path} ({size_mb:.1f} MB, {total_dur:.1f}s)")
                    return out_path
                logger.info("GPU clip failed — falling back to local pipeline")
            except Exception as e:
                logger.warning(f"GPU path error, falling back to local: {e}")

    # ── Local pipeline (fast fallback: stream-copy + single encode) ──────────
    logger.info(f"Using fast local fallback for {os.path.basename(mp4_path)}")
    if await _fast_local_clip(mp4_path, selected, segs, out_path, on_progress=on_progress):
        try:
            if on_progress:
                await on_progress("thumbnail", 0, 1)
            from thumbnail import generate_thumbnail
            best_seg = max(selected, key=lambda s: s.score) if any(s.score > 0 for s in selected) \
                       else selected[max(0, len(selected) // 4)]
            thumb = await generate_thumbnail(mp4_path, offset=best_seg.start + 1.0)
            if thumb:
                await _prepend_thumbnail(out_path, thumb)
        except Exception as e:
            logger.warning(f"Thumbnail prepend skipped: {e}")
        size_mb = os.path.getsize(out_path) / 1024 / 1024
        logger.info(f"Clip ready (fast-local): {out_path} ({size_mb:.1f} MB, {total_dur:.1f}s)")
        return out_path
    return None


async def edit_recording_multi(
    mp4_path: str,
    srt_path: str,
    count: int,
    room_name: str = "unknown",
    record_date: str = "",
    clip_duration: Optional[float] = None,
    on_progress=None,
    feedback: Optional[str] = None,
    room_id: Optional[int] = None,
    clip_engine: str = "legacy",
) -> List[str]:
    """
    Produce `count` distinct highlight clips from the same recording.
    Returns list of successfully generated output paths.
    """
    if not os.path.exists(mp4_path):
        logger.error(f"MP4 not found: {mp4_path}")
        return []
    if not os.path.exists(srt_path):
        logger.error(f"SRT not found: {srt_path}")
        return []

    # Parse + merge short segments + score once
    segs = parse_srt(srt_path)
    if not segs:
        logger.warning(f"Empty SRT: {srt_path}")
        return []
    segs = _merge_short_segs(segs)
    for seg in segs:
        score_and_tag(seg)

    # Detect silence once
    try:
        silences = await detect_silence(mp4_path)
        for seg in segs:
            if seg.valid and _silence_ratio(seg, silences) > 0.6:
                seg.valid = False
                seg.reject_reason = "silence"
    except Exception as e:
        logger.warning(f"Silence detection skipped: {e}")

    # Phase B/C/D: enrich scores once for all variants
    try:
        from segment_scorer import enrich_audio_scores
        await enrich_audio_scores(mp4_path, segs)
    except Exception as e:
        logger.warning(f"Audio scoring skipped: {e}")
    try:
        from segment_scorer import enrich_visual_scores
        await enrich_visual_scores(mp4_path, segs)
    except Exception as e:
        logger.warning(f"Visual scoring skipped: {e}")
    try:
        from segment_scorer import enrich_semantic_scores
        await enrich_semantic_scores(mp4_path, segs)
    except Exception as e:
        logger.warning(f"Semantic scoring skipped: {e}")
    try:
        from segment_scorer import enrich_llm_text_scores
        await enrich_llm_text_scores(segs, recording_id=room_id)
    except Exception as e:
        logger.warning(f"LLM text scoring skipped: {e}")

    # v2: 发型边界识别
    if clip_engine == "v2":
        try:
            from wig_boundary import detect_boundaries, pick_best_window
            boundaries = await detect_boundaries(srt_path)
            window = pick_best_window(boundaries)
            if window:
                segs = [s for s in segs if s.start >= window["start_sec"] and s.end <= window["end_sec"]]
                if not segs:
                    logger.warning("[v2 multi] No segments in wig window, falling back to all segs")
        except Exception as e:
            logger.warning(f"[v2 multi] Boundary detection error: {e}")

    # Apply feedback hints if provided
    if feedback:
        hints = await _feedback_to_hints(srt_path, feedback)
        _apply_hints(segs, hints)

    if clip_engine == "v2":
        c_min = clip_duration * 0.85 if clip_duration else CLIP_MIN_V2
        c_max = clip_duration if clip_duration else CLIP_MAX_V2
    else:
        c_min = (clip_duration * 0.85) if clip_duration else CLIP_MIN
        c_max = clip_duration if clip_duration else CLIP_MAX

    # Enforce hard floor
    c_min = max(c_min, CLIP_MIN)
    c_max = max(c_max, c_min)

    from datetime import datetime
    date_str  = record_date or datetime.utcnow().strftime("%Y%m%d")
    safe_name = re.sub(r'[\\/:*?"<>|]', '_', room_name)
    out_dir   = os.path.join(RECORDINGS_DIR, safe_name, date_str)
    os.makedirs(out_dir, exist_ok=True)
    base_seq  = len([f for f in os.listdir(out_dir) if f.endswith("_clip.mp4") or "_clip_v" in f]) + 1

    results: List[str] = []
    exclude_ids: set = set()

    for k in range(count):
        if k == 0:
            selected = _select_from_valid([s for s in segs if s.valid], c_min, c_max)
        else:
            selected = select_clips_variant(segs, exclude_ids, c_min, c_max, seed=k)

        if not selected:
            logger.warning(f"No clips selected for variant {k+1}")
            continue

        # Accumulate used segment ids to encourage variety in next variant
        exclude_ids.update(id(s) for s in selected)

        out_path = os.path.join(out_dir, f"{safe_name}_{date_str}_{base_seq:03d}_clip_v{k+1}.mp4")
        total_dur = sum(s.duration for s in selected)
        logger.info(f"Variant {k+1}: {len(selected)} segs, {total_dur:.1f}s")

        # Hard output duration gate: skip variants shorter than CLIP_MIN
        if total_dur < CLIP_MIN:
            logger.warning(
                f"Variant {k+1}: duration {total_dur:.1f}s < hard minimum {CLIP_MIN:.0f}s — skipping"
            )
            continue

        # ── Try GPU NVENC path first ──────────────────────────────────────────
        gpu_used = False
        _room_id_v = room_id  # local copy so we can disable GPU for this variant only
        if _room_id_v is not None:
            from gpu_state import is_online as _gpu_is_online, wait_until_online as _gpu_wait
            if not _gpu_is_online():
                logger.info(f"GPU offline — waiting up to {_GPU_WAIT_TIMEOUT:.0f}s (variant {k+1})...")
                try:
                    await asyncio.wait_for(_gpu_wait(), timeout=_GPU_WAIT_TIMEOUT)
                except asyncio.TimeoutError:
                    logger.warning(f"GPU still offline — using local fallback for variant {k+1}")
                    _room_id_v = None
        if _room_id_v is not None:
            try:
                mp4_filename = os.path.basename(mp4_path)
                gpu_result = await _edit_via_gpu(
                    mp4_filename, _room_id_v, selected, segs, out_path, on_progress,
                    mp4_path=mp4_path,
                )
                if gpu_result:
                    try:
                        best_seg = max(selected, key=lambda s: s.score) if any(s.score > 0 for s in selected) \
                                   else selected[max(0, len(selected) // 4)]
                        from thumbnail import generate_thumbnail
                        thumb = await generate_thumbnail(mp4_path, offset=best_seg.start + 1.0)
                        if thumb:
                            await _prepend_thumbnail(out_path, thumb)
                    except Exception as te:
                        logger.warning(f"Thumbnail prepend skipped (GPU variant {k+1}): {te}")
                    size_mb = os.path.getsize(out_path) / 1024 / 1024
                    logger.info(f"Variant {k+1} ready (NVENC): {out_path} ({size_mb:.1f} MB)")
                    results.append(out_path)
                    gpu_used = True
            except Exception as e:
                logger.warning(f"GPU path error for variant {k+1}, falling back: {e}")

        if gpu_used:
            continue

        # ── Local fallback pipeline (fast: stream-copy + single encode) ─────
        logger.info(f"Using fast local fallback for variant {k+1} of {os.path.basename(mp4_path)}")
        if on_progress:
            await on_progress("build", k, count)
        if await _fast_local_clip(mp4_path, selected, segs, out_path, on_progress=on_progress):
            try:
                if on_progress:
                    await on_progress("thumbnail", k, count)
                from thumbnail import generate_thumbnail
                best_seg = max(selected, key=lambda s: s.score) if any(s.score > 0 for s in selected) \
                           else selected[max(0, len(selected) // 4)]
                thumb = await generate_thumbnail(mp4_path, offset=best_seg.start + 1.0)
                if thumb:
                    await _prepend_thumbnail(out_path, thumb)
            except Exception as e:
                logger.warning(f"Thumbnail prepend skipped (variant {k+1}): {e}")
            size_mb = os.path.getsize(out_path) / 1024 / 1024
            logger.info(f"Variant {k+1} ready (fast-local): {out_path} ({size_mb:.1f} MB)")
            results.append(out_path)
        else:
            logger.error(f"Variant {k+1} build failed")

    return results
