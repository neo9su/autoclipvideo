"""
wig_boundary.py — 用 Claude (Bedrock) 从 SRT 字幕中识别每款发型介绍的起止时间。

返回示例：
  [
    {"wig": "氧气粒子直发", "color": "栗子棕", "start_sec": 0.0,   "end_sec": 720.0, "complete": True},
    {"wig": "赏金猎人卷发", "color": "脏橘色", "start_sec": 780.0, "end_sec": 1500.0,"complete": True},
  ]
"""

import json
import logging
import os
import re
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BEDROCK_URL   = "https://bedrock-runtime.us-east-1.amazonaws.com"
BEDROCK_MODEL = os.environ.get("BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-6")
BEDROCK_TOKEN = os.environ.get("AWS_BEARER_TOKEN_BEDROCK", "")

_PROMPT = """你是假发直播间内容分析专家。请分析以下直播字幕（包含时间戳），识别每款发型介绍的起止时间。

直播字幕（格式：秒数|字幕内容）：
{srt_timed}

判断规则：
- 一款发型介绍通常包括：产品介绍 → 佩戴演示 → 细节展示 → 转化收口，持续约10-15分钟
- 主播说"下面介绍"/"换一款"/"接下来看这款"/"好的家人们"等标志着切换
- 出现新的发型名称（大波浪、齐刘海、卷发、直发等）标志新一款开始
- "链接上车"/"扣1"/"抢购"通常是当前款的结尾

请以JSON格式返回（只返回JSON数组，不含其他文字）：
[
  {{
    "wig": "发型款式名称",
    "color": "颜色（如无明确提及填null）",
    "start_sec": 开始时间（秒，数字）,
    "end_sec": 结束时间（秒，数字）,
    "complete": true或false（是否有完整的介绍流程：产品介绍+佩戴演示+转化收口）
  }}
]

注意：如果整段录像只介绍一款发型，也正常返回一条记录。"""


def _srt_to_timed_text(srt_path: str, max_chars: int = 5000) -> str:
    """将 SRT 转成 '秒数|文本' 格式，便于 LLM 判断时间边界。"""
    if not os.path.exists(srt_path):
        return ""
    try:
        with open(srt_path, encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return ""

    blocks = re.split(r"\n\n+", content.strip())
    lines = []
    for block in blocks:
        blines = block.strip().splitlines()
        if len(blines) < 3:
            continue
        # 找时间行
        time_line = next((l for l in blines if "-->" in l), None)
        if not time_line:
            continue
        m = re.match(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})", time_line)
        if not m:
            continue
        h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
        sec = h * 3600 + mi * 60 + s
        # 字幕文字（跳过序号行和时间行）
        text_lines = [
            l for l in blines
            if l.strip() and "-->" not in l and not l.strip().isdigit()
        ]
        if text_lines:
            lines.append(f"{sec}|{''.join(text_lines)}")

    result = "\n".join(lines)
    # 均匀截断保持覆盖率
    if len(result) > max_chars:
        step = max(1, len(lines) // (max_chars // 20))
        result = "\n".join(lines[::step])[:max_chars]
    return result


async def detect_boundaries(srt_path: str) -> list[dict]:
    """
    分析 SRT，返回发型边界列表。
    失败时返回空列表（调用方应 fallback 到 legacy）。
    """
    if not BEDROCK_TOKEN:
        logger.warning("BEDROCK_TOKEN not set — skipping boundary detection")
        return []

    srt_timed = _srt_to_timed_text(srt_path)
    if not srt_timed:
        logger.warning(f"Empty SRT timed text: {srt_path}")
        return []

    payload = {
        "messages": [{
            "role": "user",
            "content": [{"text": _PROMPT.format(srt_timed=srt_timed)}],
        }],
        "inferenceConfig": {"maxTokens": 800, "temperature": 0},
    }
    url = f"{BEDROCK_URL}/model/{BEDROCK_MODEL}/converse"
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
        if resp.status_code != 200:
            logger.error(f"Bedrock boundary {resp.status_code}: {resp.text[:300]}")
            return []

        raw = resp.json()["output"]["message"]["content"][0]["text"]
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if not m:
            logger.warning(f"No JSON array in boundary response: {raw[:200]}")
            return []

        boundaries = json.loads(m.group())
        # 校验结构
        valid = []
        for b in boundaries:
            if isinstance(b, dict) and "start_sec" in b and "end_sec" in b:
                b["start_sec"] = float(b["start_sec"])
                b["end_sec"]   = float(b["end_sec"])
                b.setdefault("wig", "未知款")
                b.setdefault("color", None)
                b.setdefault("complete", False)
                if b["end_sec"] > b["start_sec"]:
                    valid.append(b)

        logger.info(
            f"Boundary detection: {len(valid)} wigs — "
            + ", ".join(f"{b['wig']}({b['start_sec']:.0f}-{b['end_sec']:.0f}s)" for b in valid)
        )
        return valid

    except Exception as e:
        logger.error(f"detect_boundaries failed: {e}")
        return []


def pick_best_window(boundaries: list[dict], min_duration: float = 120.0) -> Optional[dict]:
    """
    从边界列表中选出最适合剪辑的一款：
    优先选 complete=True 且时长最长的，其次选最长的。
    """
    if not boundaries:
        return None

    def score(b):
        dur = b["end_sec"] - b["start_sec"]
        return (1 if b.get("complete") else 0, dur)

    candidates = [b for b in boundaries if (b["end_sec"] - b["start_sec"]) >= min_duration]
    if not candidates:
        candidates = boundaries  # 全部都太短时放宽限制

    return max(candidates, key=score)
