"""
Intelligent clip editor for Douyin live recordings.

Pipeline:
  1. Parse SRT → scored segments
  2. Detect silence via ffmpeg → mark invalid
  3. Select best segments (15-30s total) with A-B-A structure
  4. Cut + concat via ffmpeg → output _clip.mp4
"""
import asyncio
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), "..", "recordings")
CLIP_MIN = 15.0   # seconds
CLIP_MAX = 30.0   # seconds

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
    # 时间词
    r'这周|上周|下周',
    r'年前|年后',
    r'今天|明天|昨天',
    r'这个月|下个月|上个月',
]

# ── Keyword scoring (higher = more valuable to keep) ─────────────────────────
_SCORES: dict[str, float] = {
    # Pain points
    '发缝宽': 10, '秃头': 10, '发量少': 10, '头型不好看': 9,
    '扁头': 9, '显脸大': 9, '贴头皮': 8,
    # Visual impact / transformation
    '秒变': 10, '小V脸': 10, '变身': 9, '背影杀': 9,
    '头包脸': 9, '高颅顶': 9, '一梳到底': 9,
    '氛围感': 8, '蓬松': 8, '变美': 8,
    # Product endorsement
    '真人发丝': 8, '递针': 8, '无痕': 8, '不掉色': 7,
    '免打理': 7, '仿真': 8,
    # Conversion urgency
    '炸福利': 10, '上车': 9, '运费险': 8,
    '不满意包退': 9, '包退': 7,
    # Contrast / before-after
    '戴上': 7, '戴之前': 8, '戴之后': 8, '对比': 8,
    # Emotion peak
    '大笑': 7, '惊讶': 7, '天啊': 7, '哇': 5,
}

# ── Segment category tags (for A-B-A structure) ───────────────────────────────
_PROBLEM_KW   = {'发缝宽', '秃头', '发量少', '扁头', '显脸大', '贴头皮', '头型不好看'}
_SOLUTION_KW  = {'真人发丝', '递针', '无痕', '不掉色', '免打理', '仿真', '一梳到底'}
_RESULT_KW    = {'秒变', '小V脸', '变身', '高颅顶', '头包脸', '背影杀', '氛围感', '变美'}
_CONVERT_KW   = {'炸福利', '上车', '运费险', '包退'}


@dataclass
class Seg:
    idx: int
    start: float
    end: float
    text: str
    score: float = 0.0
    valid: bool = True
    category: str = "neutral"   # problem / solution / result / convert / neutral

    @property
    def duration(self) -> float:
        return self.end - self.start


# ── ASS subtitle generation ────────────────────────────────────────────────────

# Map each keyword to its semantic category
_KW_TO_CAT: dict[str, str] = {}
for _kw in _PROBLEM_KW:   _KW_TO_CAT[_kw] = "problem"
for _kw in _RESULT_KW:    _KW_TO_CAT[_kw] = "result"
for _kw in _CONVERT_KW:   _KW_TO_CAT[_kw] = "convert"
for _kw in _SOLUTION_KW:  _KW_TO_CAT[_kw] = "solution"
for _kw in _SCORES:
    if _kw not in _KW_TO_CAT:
        _KW_TO_CAT[_kw] = "neutral"

# ASS colors: &HAABBGGRR& (AA=00 opaque; bytes in Blue-Green-Red order)
_KW_COLORS: dict[str, str] = {
    "problem":  "&H000055FF&",   # orange-red  #FF5500
    "result":   "&H0000D7FF&",   # gold        #FFD700
    "convert":  "&H0044FF00&",   # lime green  #00FF44
    "solution": "&H00FFDD00&",   # cyan        #00DDFF
    "neutral":  "&H0000CCFF&",   # yellow      #FFCC00
}

_ASS_HEADER = """\
[Script Info]
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 720
PlayResY: 1280

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Microsoft YaHei,58,&H00FFFFFF,&H000000FF,&H00141414,&H80000000,0,0,0,0,100,100,1,0,1,4,1.5,2,40,40,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _sec_to_ass(s: float) -> str:
    s = max(0.0, s)
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    return f"{h}:{m:02d}:{sec:05.2f}"


def _annotate_text(text: str) -> tuple[str, bool]:
    """Wrap scoring keywords in ASS color+bold tags. Returns (tagged_text, had_keyword)."""
    kws = sorted(_KW_TO_CAT.keys(), key=len, reverse=True)
    has_kw = False
    for kw in kws:
        if kw in text:
            color = _KW_COLORS[_KW_TO_CAT[kw]]
            open_tag  = "{" + "\\c" + color + "\\b1" + "}"
            close_tag = "{\\r}"
            text = text.replace(kw, open_tag + kw + close_tag, 1)
            has_kw = True
    return text, has_kw


_ANIM_STYLES = [
    # style 1: gentle scale pulse
    r"{\fad(120,80)\t(0,300,\fscx105\fscy105)\t(300,600,\fscx100\fscy100)}",
    # style 2: slide up from below (approximate via pos)
    r"{\fad(100,80)\t(0,200,\fscx102\fscy102)\t(200,400,\fscx100\fscy100)}",
    # style 3: bounce
    r"{\fad(80,60)\t(0,150,\fscx108\fscy108)\t(150,300,\fscx97\fscy97)\t(300,450,\fscx103\fscy103)\t(450,600,\fscx100\fscy100)}",
    # style 4: color pulse (yellow → white)
    r"{\fad(100,80)\t(0,300,\c&H00FFFF44&)\t(300,600,\c&H00FFFFFF&)}",
]
_ANIM_KW = r"{\fad(150,100)\t(0,200,\fscx112\fscy112)\t(200,400,\fscx100\fscy100)}"


def build_ass(selected: List[Seg], all_segs: List[Seg]) -> str:
    """
    Generate ASS subtitle string with keyword highlights.
    Remaps SRT timestamps to the clip's output timeline.
    Keyword lines get a scale-bounce entry animation; plain lines cycle 4 styles.
    """
    dialogue: list[str] = []
    cursor = 0.0
    line_idx = 0
    for sel_seg in selected:
        offset = cursor
        cursor += sel_seg.duration
        for srt in all_segs:
            ov_start = max(srt.start, sel_seg.start)
            ov_end   = min(srt.end,   sel_seg.end)
            if ov_end - ov_start < 0.1:
                continue
            t0 = offset + (ov_start - sel_seg.start)
            t1 = offset + (ov_end   - sel_seg.start)
            annotated, has_kw = _annotate_text(srt.text)
            if has_kw:
                prefix = _ANIM_KW
            else:
                prefix = _ANIM_STYLES[line_idx % len(_ANIM_STYLES)]
            line_idx += 1
            dialogue.append(
                f"Dialogue: 0,{_sec_to_ass(t0)},{_sec_to_ass(t1)},"
                f"Default,,0,0,0,,{prefix}{annotated}"
            )
    return _ASS_HEADER + "\n".join(dialogue) + "\n"


FADE_DUR = 0.3
TRANSITIONS = ["fade", "slideright", "slideleft", "dissolve"]


async def _build_clip(mp4: str, selected: List[Seg], segs: List[Seg], out: str) -> bool:
    """Single-pass ffmpeg: fast-seek N inputs + trim filter (frame-accurate) + xfade + ass burn."""
    n = len(selected)
    ass_content = build_ass(selected, segs)
    has_subs = "Dialogue:" in ass_content

    with tempfile.TemporaryDirectory() as tmp:
        ass_path = os.path.join(tmp, "subs.ass")
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)

        cmd = ["ffmpeg", "-y"]
        for seg in selected:
            pre = max(0.0, seg.start - 3.0)
            cmd += ["-ss", f"{pre:.3f}", "-i", mp4]

        parts = []
        for i, seg in enumerate(selected):
            pre = max(0.0, seg.start - 3.0)
            fs  = seg.start - pre           # fine_start ≤ 3.0
            fe  = fs + (seg.end - seg.start)
            parts.append(f"[{i}:v]trim={fs:.3f}:{fe:.3f},setpts=PTS-STARTPTS,scale=-2:720[v{i}]")
            parts.append(f"[{i}:a]atrim={fs:.3f}:{fe:.3f},asetpts=PTS-STARTPTS[a{i}]")

        # xfade chain instead of concat
        if n == 1:
            parts += ["[v0]copy[vcat]", "[a0]acopy[acat]"]
        else:
            cur_v, cur_a, v_off = "v0", "a0", 0.0
            for i in range(1, n):
                tr = TRANSITIONS[(i - 1) % len(TRANSITIONS)]
                v_off += selected[i - 1].duration - FADE_DUR
                parts.append(f"[{cur_v}][v{i}]xfade=transition={tr}:duration={FADE_DUR}:offset={v_off:.3f}[xfv{i}]")
                parts.append(f"[{cur_a}][a{i}]acrossfade=d={FADE_DUR}[xfa{i}]")
                cur_v, cur_a = f"xfv{i}", f"xfa{i}"
            parts += [f"[{cur_v}]copy[vcat]", f"[{cur_a}]acopy[acat]"]

        if has_subs:
            # filter_complex uses backslash escaping, not shell quotes
            escaped = ass_path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
            parts.append(f"[vcat]ass={escaped}[vout]")
            vmap = "[vout]"
        else:
            vmap = "[vcat]"

        cmd += [
            "-filter_complex", ";".join(parts),
            "-map", vmap, "-map", "[acat]",
            "-c:v", "libx264", "-crf", "22", "-preset", "veryfast",
            "-c:a", "aac", "-b:a", "128k",
            out,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        ok = proc.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0
        if not ok:
            logger.error(f"_build_clip failed: {stderr.decode()[-300:]}")
        return ok


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

def score_and_tag(seg: Seg) -> None:
    text = seg.text

    # Remove check
    for pat in _REMOVE_PATTERNS:
        if re.search(pat, text):
            seg.valid = False
            return

    # Too short to be useful
    if seg.duration < 0.4:
        seg.valid = False
        return

    # Keyword score
    score = 0.0
    for kw, pts in _SCORES.items():
        if kw in text:
            score += pts

    # Boost punchy short segments
    if 1.0 <= seg.duration <= 4.0:
        score *= 1.2

    seg.score = round(score, 2)

    # Category tag (A-B-A)
    if any(kw in text for kw in _PROBLEM_KW):
        seg.category = "problem"
    elif any(kw in text for kw in _SOLUTION_KW):
        seg.category = "solution"
    elif any(kw in text for kw in _RESULT_KW):
        seg.category = "result"
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


def select_clips(segs: List[Seg]) -> List[Seg]:
    valid = [s for s in segs if s.valid]
    if not valid:
        return []

    # Budget allocation: 20% opening, 30% problem, 25% solution, 25% result/convert
    opening_budget  = CLIP_MAX * 0.20
    problem_budget  = CLIP_MAX * 0.30
    solution_budget = CLIP_MAX * 0.25
    result_budget   = CLIP_MAX * 0.25

    # Golden opening: single highest-score segment (prefer result/transform)
    opening_pool = sorted(
        [s for s in valid if s.category in ("result", "convert") and s.score > 0],
        key=lambda s: s.score, reverse=True
    ) or sorted(valid, key=lambda s: s.score, reverse=True)
    opening = [opening_pool[0]] if opening_pool and opening_pool[0].duration <= opening_budget else []

    # A-B-A segments
    exclude = {id(s) for s in opening}
    remaining = [s for s in valid if id(s) not in exclude]

    def pick(cat, budget):
        pool = sorted(
            [s for s in remaining if s.category == cat],
            key=lambda s: s.score, reverse=True
        )
        chosen, used = [], 0.0
        for s in pool:
            if used + s.duration <= budget:
                chosen.append(s)
                used += s.duration
        return chosen

    problems  = pick("problem",  problem_budget)
    solutions = pick("solution", solution_budget)
    results   = pick("result",   result_budget)
    converts  = pick("convert",  CLIP_MAX * 0.15)

    assembled = opening + problems + solutions + results + converts
    total = sum(s.duration for s in assembled)

    # If under minimum, fill with highest-score neutrals
    if total < CLIP_MIN:
        used_ids = {id(s) for s in assembled}
        neutrals = sorted(
            [s for s in valid if id(s) not in used_ids],
            key=lambda s: s.score, reverse=True
        )
        for s in neutrals:
            if total >= CLIP_MAX:
                break
            assembled.append(s)
            total += s.duration

    # Sort assembled (keep opening first, rest by original time order)
    if len(assembled) > 1:
        head = assembled[0]
        tail = sorted(assembled[1:], key=lambda s: s.start)
        assembled = [head] + tail

    # Trim to CLIP_MAX
    final, total = [], 0.0
    for s in assembled:
        if total + s.duration > CLIP_MAX:
            break
        final.append(s)
        total += s.duration

    return final


# ── Main entry ────────────────────────────────────────────────────────────────

async def edit_recording(mp4_path: str, srt_path: str, room_name: str = "unknown", record_date: str = "") -> Optional[str]:
    """
    Produce a 15-30s highlight clip from a recording + its SRT.
    Returns local path to the output _clip.mp4, or None on failure.
    Output is organised as recordings/{room_name}/{date}/{room}_{date}_{seq}_clip.mp4.
    """
    if not os.path.exists(mp4_path):
        logger.error(f"MP4 not found: {mp4_path}")
        return None
    if not os.path.exists(srt_path):
        logger.error(f"SRT not found: {srt_path}")
        return None

    # Parse + score
    segs = parse_srt(srt_path)
    if not segs:
        logger.warning(f"Empty SRT: {srt_path}")
        return None
    for seg in segs:
        score_and_tag(seg)

    # Detect silence and penalize silent segments
    try:
        silences = await detect_silence(mp4_path)
        for seg in segs:
            if seg.valid and _silence_ratio(seg, silences) > 0.6:
                seg.valid = False
                logger.debug(f"Silence removed: [{seg.start:.1f}-{seg.end:.1f}] {seg.text[:30]}")
    except Exception as e:
        logger.warning(f"Silence detection skipped: {e}")

    # Select clips
    selected = select_clips(segs)
    if not selected:
        logger.warning(f"No valid clips selected for {mp4_path}")
        return None

    total_dur = sum(s.duration for s in selected)
    logger.info(
        f"Selected {len(selected)} segments, {total_dur:.1f}s "
        f"[{', '.join(s.category for s in selected)}]"
    )

    from datetime import datetime
    date_str  = record_date or datetime.utcnow().strftime("%Y%m%d")
    safe_name = re.sub(r'[\\/:*?"<>|]', '_', room_name)
    out_dir   = os.path.join(RECORDINGS_DIR, safe_name, date_str)
    os.makedirs(out_dir, exist_ok=True)
    seq       = len([f for f in os.listdir(out_dir) if f.endswith("_clip.mp4")]) + 1
    out_path  = os.path.join(out_dir, f"{safe_name}_{date_str}_{seq:03d}_clip.mp4")

    if await _build_clip(mp4_path, selected, segs, out_path):
        size_mb = os.path.getsize(out_path) / 1024 / 1024
        logger.info(f"Clip ready: {out_path} ({size_mb:.1f} MB, {total_dur:.1f}s)")
        return out_path
    return None
