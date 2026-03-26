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
CLIP_MIN = 46.0   # seconds
CLIP_MAX = 240.0  # seconds
MAX_CLIP_SEGMENTS = 50  # cap to avoid ffmpeg resource exhaustion
SEG_PAD = 0.5     # seconds of audio/video to retain before/after each SRT segment

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


# ── ASS subtitle style pool ───────────────────────────────────────────────────
# Each tuple: (style_name, fontname, fontsize, bold, italic, spacing, outline, shadow)
# Fonts: PingFang SC=clean; STHeiti=bold; Xingkai SC=brush; Yuanti SC=round;
#        STKaiti=calligraphy; Baoli SC=slab; Microsoft YaHei=modern
_SUBTITLE_STYLES = [
    ("Clean",   "PingFang SC",     92,  0, 0,  1, 7, 2),
    ("Bold",    "STHeiti",         100, 1, 0,  0, 9, 3),
    ("Brush",   "Xingkai SC",      102, 1, 0,  2, 6, 3),
    ("Round",   "Yuanti SC",       96,  0, 0,  2, 6, 2),
    ("Kaiti",   "STKaiti",         96,  0, 1,  1, 7, 2),
    ("Slab",    "Baoli SC",        98,  0, 0,  1, 8, 3),
    ("Modern",  "Microsoft YaHei", 96,  0, 0,  1, 7, 2),
]

def _build_ass_styles() -> str:
    """Build the [V4+ Styles] section with all font variants."""
    fmt = "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
    lines = [fmt]
    for name, font, size, bold, italic, spacing, outline, shadow in _SUBTITLE_STYLES:
        lines.append(
            f"Style: {name},{font},{size},"
            f"&H00FFFFFF,&H000000FF,&H00141414,&H80000000,"
            f"{bold},{italic},0,0,100,100,{spacing},0,1,{outline},{shadow},2,80,80,120,1\n"
        )
    return "".join(lines)

_STYLE_NAMES = [s[0] for s in _SUBTITLE_STYLES]

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
    Each segment picks a random font style; keyword lines get a stronger bounce.
    """
    header = _make_ass_header()
    dialogue: list[str] = []
    cursor = 0.0
    line_idx = 0
    rng = random.Random()
    for sel_seg in selected:
        offset = cursor
        pad_b = min(SEG_PAD, sel_seg.start)   # actual pre-buffer for this segment
        cursor += pad_b + sel_seg.duration + SEG_PAD
        # Pick one style for the entire segment (visual consistency within a scene)
        seg_style = rng.choice(_STYLE_NAMES)
        for srt in all_segs:
            ov_start = max(srt.start, sel_seg.start)
            ov_end   = min(srt.end,   sel_seg.end)
            if ov_end - ov_start < 0.1:
                continue
            # pad_b shifts speech forward in the output timeline (after pre-buffer)
            t0 = offset + pad_b + (ov_start - sel_seg.start)
            t1 = offset + pad_b + (ov_end   - sel_seg.start)
            annotated, has_kw = _annotate_text(srt.text)
            if has_kw:
                prefix = _ANIM_KW
            else:
                prefix = _ANIM_STYLES[line_idx % len(_ANIM_STYLES)]
            line_idx += 1
            dialogue.append(
                f"Dialogue: 0,{_sec_to_ass(t0)},{_sec_to_ass(t1)},"
                f"{seg_style},,0,0,0,,{prefix}{annotated}"
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

# Transition pool – cycled across segment boundaries, 5 visual styles:
#   前后叠加: dissolve / fade
#   聚焦:     zoomin / radial / hblur
#   画中画:   squeezeh / squeezev
#   人物重叠: fadeblack  (rembg gives true BG separation)
#   运镜:     zoom_punch (snap zoom-in to face, snap back)
_TR_POOL = [
    "dissolve",    # 前后叠加
    "zoomin",      # 聚焦
    "squeezeh",    # 画中画
    "fadeblack",   # 人物重叠
    "zoom_punch",  # 运镜
    "fade",        # 前后叠加
    "radial",      # 聚焦
    "hblur",       # 聚焦
    "squeezev",    # 画中画
]


async def _preprocess_segments(mp4: str, selected: List[Seg], tmp_dir: str, on_progress=None) -> List[Optional[str]]:
    """Pre-encode each segment to 4K temp file in parallel to reduce filter-graph memory.
    Audio: apply noisereduce (voice isolation) when available, else ffmpeg-only denoising.
    Video: lanczos upscale + mild sharpening.
    """
    _SF = (
        f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=decrease:flags=lanczos,"
        f"pad={OUT_W}:{OUT_H}:(ow-iw)/2:(oh-ih)/2,"
        f"unsharp=5:5:0.6:5:5:0.0"   # mild luma sharpening
    )

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

        if has_denoised:
            cmd = [
                "ffmpeg", "-y",
                "-ss", f"{pre:.3f}", "-i", mp4,
                "-i", denoised_wav,
                "-vf", f"trim={fs:.3f}:{fe:.3f},setpts=PTS-STARTPTS,{_SF},fps=25",
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
                "-vf", f"trim={fs:.3f}:{fe:.3f},setpts=PTS-STARTPTS,{_SF},fps=25",
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
            tr = _TR_POOL[bi % len(_TR_POOL)]
            xfade_tr = "dissolve" if tr == "zoom_punch" else tr
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
                    import httpx as _httpx
                    with open(frame_tmp, "rb") as _f:
                        _img_data = _f.read()
                    async with _httpx.AsyncClient(timeout=30.0) as _c:
                        _r = await _c.post(
                            f"{_GPU_SERVICE_URL}/rembg",
                            files={"file": ("frame.jpg", _img_data, "image/jpeg")},
                        )
                    if _r.status_code == 200:
                        with open(person_tmp, "wb") as _f:
                            _f.write(_r.content)
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
                await asyncio.get_event_loop().run_in_executor(None, _remove_bg)
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
            return

    # Too short to be useful (min 3s per scene)
    if seg.duration < 3.0:
        seg.valid = False
        return

    # Trim over-long segments (max 6s per scene)
    if seg.duration > 6.0:
        seg.end = seg.start + 6.0

    # Keyword score
    score = 0.0
    for kw, pts in _SCORES.items():
        if kw in text:
            score += pts

    # Boost punchy short segments (3–4s sweet spot)
    if 3.0 <= seg.duration <= 4.0:
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


def _select_from_valid(valid: List[Seg], clip_min: float = CLIP_MIN, clip_max: float = CLIP_MAX) -> List[Seg]:
    """Core A-B-A selection logic from a pre-filtered valid segment list."""
    if not valid:
        return []

    # Budget allocation: 20% opening, 30% problem, 25% solution, 25% result/convert
    opening_budget  = clip_max * 0.20
    problem_budget  = clip_max * 0.30
    solution_budget = clip_max * 0.25
    result_budget   = clip_max * 0.25

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
    converts  = pick("convert",  clip_max * 0.15)

    assembled = opening + problems + solutions + results + converts
    total = sum(s.duration for s in assembled)

    # If under minimum, fill with highest-score neutrals
    if total < clip_min:
        used_ids = {id(s) for s in assembled}
        neutrals = sorted(
            [s for s in valid if id(s) not in used_ids],
            key=lambda s: s.score, reverse=True
        )
        for s in neutrals:
            if total >= clip_max:
                break
            assembled.append(s)
            total += s.duration

    # Sort assembled (keep opening first, rest by original time order)
    if len(assembled) > 1:
        head = assembled[0]
        tail = sorted(assembled[1:], key=lambda s: s.start)
        assembled = [head] + tail

    # Trim to clip_max
    final, total = [], 0.0
    for s in assembled:
        if total + s.duration > clip_max:
            break
        final.append(s)
        total += s.duration

    # Cap segment count to avoid ffmpeg resource exhaustion
    if len(final) > MAX_CLIP_SEGMENTS:
        final = sorted(final, key=lambda s: s.score, reverse=True)[:MAX_CLIP_SEGMENTS]
        final = sorted(final, key=lambda s: s.start)

    return final


def select_clips(segs: List[Seg], clip_min: float = CLIP_MIN, clip_max: float = CLIP_MAX) -> List[Seg]:
    valid = [s for s in segs if s.valid]
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
        # Time-range preferences
        mid = (seg.start + seg.end) / 2
        for s, e in preferred:
            if s <= mid <= e:
                seg.score += 4.0
        for s, e in avoided:
            if s <= mid <= e:
                seg.valid = False


# ── GPU offload path ──────────────────────────────────────────────────────────

_GPU_SERVICE_URL  = os.environ.get("GPU_SERVICE_URL",  "http://10.190.0.203:8877")
_GPU_WAIT_TIMEOUT = float(os.environ.get("GPU_WAIT_TIMEOUT", "600"))  # seconds to wait for GPU before local fallback


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
    import httpx

    ass_content = build_ass(selected, segs)
    best_seg = max(selected, key=lambda s: s.score) if any(s.score > 0 for s in selected) \
               else selected[max(0, len(selected) // 4)]

    payload = {
        "mp4_filename": mp4_filename,
        "room_id": room_id,
        "segments": [{"start": s.start, "end": s.end} for s in selected],
        "ass_content": ass_content,
        "thumb_seek": best_seg.start + 1.0,
    }

    async def _submit(client) -> Optional[str]:
        """POST /clip-jobs; returns job_id or None."""
        nonlocal mp4_path
        try:
            resp = await client.post(f"{_GPU_SERVICE_URL}/clip-jobs", json=payload)
        except Exception as e:
            logger.warning(f"GPU clip job submission failed: {e}")
            return None
        if resp.status_code == 404 and mp4_path and os.path.exists(mp4_path):
            # File not on GPU server — upload it, then retry once
            logger.info(f"GPU 404: auto-uploading {mp4_filename} to GPU server then retrying...")
            try:
                from sync import sync_file
                await sync_file(mp4_path, room_id)
            except Exception as ue:
                logger.warning(f"Auto-upload for {mp4_filename} failed: {ue}")
                return None
            try:
                resp = await client.post(f"{_GPU_SERVICE_URL}/clip-jobs", json=payload)
            except Exception as e:
                logger.warning(f"GPU clip job retry after upload failed: {e}")
                return None
        if resp.status_code != 201:
            logger.warning(f"GPU clip job rejected: {resp.status_code} {resp.text[:200]}")
            return None
        jid = resp.json()["job_id"]
        logger.info(f"GPU clip job created: {jid} for {mp4_filename}")
        return jid

    async with httpx.AsyncClient(timeout=30.0) as client:
        job_id = await _submit(client)
    if not job_id:
        return None

    # Poll until done or 25-minute timeout; recover if GPU goes offline mid-job
    deadline = asyncio.get_event_loop().time() + 1500
    consecutive_errors = 0
    async with httpx.AsyncClient(timeout=15.0) as client:
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(5.0)
            try:
                data = (await client.get(f"{_GPU_SERVICE_URL}/clip-jobs/{job_id}")).json()
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
                            r = await client.get(f"{_GPU_SERVICE_URL}/clip-jobs/{job_id}")
                            if r.status_code == 404:
                                # Job was lost in restart — resubmit
                                logger.info(f"Clip job {job_id} lost after GPU restart, resubmitting...")
                                async with httpx.AsyncClient(timeout=30.0) as sc:
                                    new_jid = await _submit(sc)
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
        async with httpx.AsyncClient(timeout=300.0) as client:
            r = await client.get(f"{_GPU_SERVICE_URL}/clip-jobs/{job_id}/mp4")
            if r.status_code != 200:
                logger.warning(f"GPU clip download failed: {r.status_code}")
                return None
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "wb") as f:
                f.write(r.content)
    except Exception as e:
        logger.warning(f"GPU clip download error: {e}")
        return None

    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        logger.warning("GPU clip download produced empty file")
        return None

    size_mb = os.path.getsize(out_path) / 1024 / 1024
    logger.info(f"GPU clip downloaded: {out_path} ({size_mb:.1f} MB)")
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

async def edit_recording(mp4_path: str, srt_path: str, room_name: str = "unknown", record_date: str = "", clip_duration: Optional[float] = None, on_progress=None, feedback: Optional[str] = None, room_id: Optional[int] = None) -> Optional[str]:
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
                logger.debug(f"Silence removed: [{seg.start:.1f}-{seg.end:.1f}] {seg.text[:30]}")
    except Exception as e:
        logger.warning(f"Silence detection skipped: {e}")

    # Apply feedback hints if provided
    if feedback:
        hints = await _feedback_to_hints(srt_path, feedback)
        _apply_hints(segs, hints)
        c_min = hints.get("clip_min_override") or ((clip_duration * 0.85) if clip_duration else CLIP_MIN)
        c_max = hints.get("clip_max_override") or (clip_duration if clip_duration else CLIP_MAX)
        if hints.get("prefer_longer"):
            c_min = max(c_min, CLIP_MIN * 1.3)
    else:
        c_min = (clip_duration * 0.85) if clip_duration else CLIP_MIN
        c_max = clip_duration if clip_duration else CLIP_MAX

    # Select clips
    selected = select_clips(segs, clip_min=c_min, clip_max=c_max)
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
    except Exception as e:
        logger.warning(f"Silence detection skipped: {e}")

    # Apply feedback hints if provided
    if feedback:
        hints = await _feedback_to_hints(srt_path, feedback)
        _apply_hints(segs, hints)

    c_min = (clip_duration * 0.85) if clip_duration else CLIP_MIN
    c_max = clip_duration if clip_duration else CLIP_MAX

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
