"""
clip_analyzer.py — 智能视频分析，用 Claude Vision (Bedrock) 全面解析短视频构成。

采帧策略：
  - 封面帧 (t=0s)          → 封面设计分析
  - 场景切点密集帧          → 转场动画分析
  - 字幕时间点帧            → 字幕字体/颜色/动画分析
  - 均匀帧 (每N秒一帧)     → 发型/艺术字/构图分析
  - 音频分析 (ffmpeg)       → BGM/节奏/音效时间轴
"""

import asyncio
import base64
import json
import logging
import os
import re
import tempfile
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BEDROCK_URL   = "https://bedrock-runtime.us-east-1.amazonaws.com"
BEDROCK_MODEL = os.environ.get("BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-6")
BEDROCK_TOKEN = os.environ.get("AWS_BEARER_TOKEN_BEDROCK", "")

MAX_TOTAL_FRAMES = 24   # Bedrock 单次请求图片上限

# ── 采帧 ──────────────────────────────────────────────────────────────────────

async def _run(cmd: list) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, (stdout + stderr).decode(errors="replace")


async def _get_duration(video_path: str) -> float:
    rc, out = await _run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", video_path,
    ])
    try:
        return float(out.strip())
    except Exception:
        return 0.0


async def _extract_scene_cuts(video_path: str, threshold: float = 0.35) -> list[float]:
    """返回场景切换时间点列表（秒）。"""
    rc, out = await _run([
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"select='gt(scene,{threshold})',metadata=print:file=-",
        "-an", "-f", "null", "-",
    ])
    times = []
    for m in re.finditer(r"pts_time:([\d.]+)", out):
        times.append(float(m.group(1)))
    return sorted(times)


def _parse_srt_times(srt_path: str) -> list[float]:
    """解析 SRT 字幕，返回每条字幕开始时间（秒）。"""
    if not srt_path or not os.path.exists(srt_path):
        return []
    times = []
    try:
        with open(srt_path, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->", line)
                if m:
                    h, mi, s, ms = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                    times.append(h * 3600 + mi * 60 + s + ms / 1000)
    except Exception:
        pass
    return times


async def _extract_frame_at(video_path: str, t: float, out_path: str) -> bool:
    """提取指定时间点的帧到 out_path。"""
    rc, _ = await _run([
        "ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", video_path,
        "-vframes", "1", "-q:v", "3",
        "-vf", "scale=768:-2",
        out_path,
    ])
    return rc == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0


async def collect_frames(
    video_path: str,
    srt_path: Optional[str],
    duration: float,
) -> list[tuple[float, str, str]]:
    """
    智能采帧，返回 [(时间秒, 文件路径, 帧类型), ...]。
    帧类型：cover / cut / subtitle / uniform
    """
    out_dir = tempfile.mkdtemp(prefix="clip_frames_")
    results: list[tuple[float, str, str]] = []
    seen_times: set = set()

    async def _add(t: float, ftype: str):
        # 去重：同一秒内只取一帧
        key = round(t, 1)
        if key in seen_times:
            return
        seen_times.add(key)
        path = os.path.join(out_dir, f"{ftype}_{len(results):03d}_{int(t*10):06d}.jpg")
        if await _extract_frame_at(video_path, t, path):
            results.append((t, path, ftype))

    # 1. 封面帧
    await _add(0.0, "cover")
    if duration > 1.0:
        await _add(0.5, "cover")

    # 2. 场景切点帧（每个切点前后各取一帧）
    cuts = await _extract_scene_cuts(video_path)
    for ct in cuts[:12]:
        await _add(max(0, ct - 0.1), "cut")
        await _add(ct + 0.1, "cut")

    # 3. 字幕时间点帧（每隔1条取一帧，避免过密）
    sub_times = _parse_srt_times(srt_path)
    for i, st in enumerate(sub_times):
        if i % 3 == 0 and st < duration:
            await _add(st + 0.05, "subtitle")

    # 4. 均匀帧（每5秒一帧）
    step = max(3.0, duration / 10)
    t = step
    while t < duration - 1:
        await _add(t, "uniform")
        t += step

    # 按时间排序，限制总帧数
    results.sort(key=lambda x: x[0])
    if len(results) > MAX_TOTAL_FRAMES:
        # 优先保留 cover 和 cut 帧
        priority = [r for r in results if r[2] in ("cover", "cut")]
        others   = [r for r in results if r[2] not in ("cover", "cut")]
        keep = priority[:MAX_TOTAL_FRAMES]
        remaining = MAX_TOTAL_FRAMES - len(keep)
        if remaining > 0:
            step2 = max(1, len(others) // remaining)
            keep += others[::step2][:remaining]
        results = sorted(keep, key=lambda x: x[0])[:MAX_TOTAL_FRAMES]

    logger.info(
        f"Collected {len(results)} frames "
        f"(cover={sum(1 for r in results if r[2]=='cover')}, "
        f"cut={sum(1 for r in results if r[2]=='cut')}, "
        f"sub={sum(1 for r in results if r[2]=='subtitle')}, "
        f"uniform={sum(1 for r in results if r[2]=='uniform')})"
    )
    return results, out_dir


# ── 音频分析 ──────────────────────────────────────────────────────────────────

async def analyze_audio(video_path: str) -> dict:
    """用 ffmpeg 提取音频特征：响度/静音/节奏感。"""
    result = {"has_bgm": False, "silence_ratio": 1.0, "rhythm": "未知", "comment": ""}

    # 静音检测
    rc, out = await _run([
        "ffmpeg", "-y", "-i", video_path,
        "-af", "silencedetect=n=-35dB:d=0.3",
        "-f", "null", "-",
    ])
    silence_starts = re.findall(r"silence_start:\s*([\d.]+)", out)
    silence_ends   = re.findall(r"silence_end:\s*([\d.]+)", out)
    silence_dur = sum(
        float(e) - float(s)
        for s, e in zip(silence_starts, silence_ends)
    )

    # 总时长
    rc2, dur_out = await _run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", video_path,
    ])
    try:
        total_dur = float(dur_out.strip())
    except Exception:
        total_dur = 60.0

    silence_ratio = min(1.0, silence_dur / total_dur) if total_dur > 0 else 1.0
    has_bgm = silence_ratio < 0.6

    # 响度统计（R128）
    rc3, loud_out = await _run([
        "ffmpeg", "-y", "-i", video_path,
        "-af", "ebur128=peak=true",
        "-f", "null", "-",
    ])
    integrated = None
    m = re.search(r"I:\s*([-\d.]+)\s*LUFS", loud_out)
    if m:
        integrated = float(m.group(1))

    # 判断节奏感（用音量变化频率粗估）
    volume_changes = len(re.findall(r"silence_start|silence_end", out))
    if volume_changes > 20:
        rhythm = "快节奏（频繁切换）"
    elif volume_changes > 8:
        rhythm = "中节奏"
    else:
        rhythm = "慢节奏或持续背景音"

    result = {
        "has_bgm": has_bgm,
        "silence_ratio": round(silence_ratio, 2),
        "rhythm": rhythm,
        "loudness_lufs": integrated,
        "comment": f"{'有背景音乐' if has_bgm else '静音较多'}，{rhythm}，响度约 {integrated:.0f} LUFS" if integrated else "",
    }
    return result


# ── 分析 Prompt ───────────────────────────────────────────────────────────────

_PROMPT = """你是抖音假发直播短视频的专业分析师。以下图片是一段短视频的关键帧截图（按时间顺序排列），请结合提供的字幕文本和音频特征，给出详细的视频构成分析。

字幕文本：
{srt_text}

音频分析数据：
{audio_info}

帧标注说明：
- [封面] 第0秒帧
- [切点] 场景切换处的帧
- [字幕] 字幕出现时的帧
- [均匀] 均匀采样帧

请以JSON格式返回完整分析（只返回JSON，不含其他文字）：
{{
  "overall_score": 综合评分1-10,

  "hairstyle": {{
    "model": "发型款式名称",
    "color": "颜色描述",
    "length": "发长（短发/中长发/长发）",
    "texture": "发质感（顺直/自然卷/大波浪等）",
    "presentation_score": 1-10,
    "comment": "发型展示效果评价"
  }},

  "cover_design": {{
    "score": 1-10,
    "layout": "构图描述（人物位置、文字位置）",
    "text_content": "封面文字内容",
    "text_style": "字体风格描述（大小/颜色/特效）",
    "color_scheme": "整体配色",
    "background": "背景处理方式",
    "comment": "封面设计评价"
  }},

  "subtitles": {{
    "score": 1-10,
    "font_style": "字体风格（粗体/细体/手写体等）",
    "color": "字幕颜色",
    "border_shadow": "描边/阴影处理",
    "position": "字幕位置（底部居中/左下等）",
    "animation": "动画效果（逐字出现/弹跳/淡入等，如无动画特征填'静态'）",
    "size": "字号感觉（大/中/小）",
    "comment": "字幕效果评价"
  }},

  "transitions": {{
    "types_found": ["识别到的转场类型，如：硬切、淡入淡出、推镜、拉镜、缩放、旋转等"],
    "total_cuts": 估计总切换次数,
    "avg_shot_duration": 估计平均镜头时长秒数,
    "pacing": "剪辑节奏描述（快/中/慢）",
    "comment": "转场风格评价"
  }},

  "artistic_text": {{
    "present": true或false,
    "position": "位置描述（右上角/左上角/画面中部等）",
    "font_style": "艺术字体风格",
    "color": "颜色",
    "animation": "动画效果（跳动/旋转/闪烁/静态等）",
    "keywords": ["出现的关键词"],
    "comment": "艺术字效果评价"
  }},

  "audio": {{
    "has_bgm": true或false,
    "bgm_style": "音乐风格（轻快/抒情/电音/无BGM等）",
    "rhythm_match": "音乐节奏与画面切换的配合度（好/一般/差）",
    "sound_effects": ["识别到的音效类型，如：转场音效/点击音/强调音等"],
    "comment": "音频整体评价"
  }},

  "narrative_structure": {{
    "score": 1-10,
    "stages_found": ["发现的叙事阶段"],
    "missing_stages": ["缺失的关键阶段"],
    "hook_quality": "开头钩子质量（强/中/弱）",
    "cta_quality": "结尾转化话术质量（强/中/弱）",
    "comment": "叙事结构简评"
  }},

  "conversion_potential": {{
    "score": 1-10,
    "strong_points": ["转化优势"],
    "weak_points": ["转化弱点"],
    "comment": "转化潜力简评"
  }},

  "improvement_suggestions": [
    "具体改进建议1",
    "具体改进建议2",
    "具体改进建议3",
    "具体改进建议4"
  ]
}}"""


# ── SRT 工具 ──────────────────────────────────────────────────────────────────

def _load_srt(srt_path: str, max_chars: int = 3000) -> str:
    if not srt_path or not os.path.exists(srt_path):
        return "（无字幕文件）"
    try:
        with open(srt_path, encoding="utf-8") as f:
            raw = f.read()
        lines = [
            l.strip() for l in raw.splitlines()
            if l.strip() and not l.strip().isdigit() and "-->" not in l
        ]
        return " ".join(lines)[:max_chars]
    except Exception:
        return "（字幕读取失败）"


# ── 主入口 ────────────────────────────────────────────────────────────────────

async def analyze_clip(
    video_path: str,
    srt_path: Optional[str] = None,
) -> Optional[dict]:
    """
    主入口：智能采帧 + 音频分析 → Claude Vision → 返回完整分析 dict。
    """
    if not BEDROCK_TOKEN:
        logger.error("AWS_BEARER_TOKEN_BEDROCK not set")
        return None
    if not os.path.exists(video_path):
        logger.error(f"Video not found: {video_path}")
        return None

    duration = await _get_duration(video_path)
    if duration <= 0:
        logger.error(f"Cannot read duration: {video_path}")
        return None

    logger.info(f"Analyzing {os.path.basename(video_path)} ({duration:.1f}s)")

    # 并行：采帧 + 音频分析
    frames_task = asyncio.create_task(collect_frames(video_path, srt_path, duration))
    audio_task  = asyncio.create_task(analyze_audio(video_path))
    (frames, out_dir), audio_info = await asyncio.gather(frames_task, audio_task)

    if not frames:
        logger.error("No frames collected")
        return None

    srt_text = _load_srt(srt_path)

    # 构建消息内容
    content = []
    for t, path, ftype in frames:
        label_map = {"cover": "封面", "cut": "切点", "subtitle": "字幕", "uniform": "均匀"}
        label = label_map.get(ftype, ftype)
        # 帧标注文字
        content.append({"text": f"[{label} {t:.1f}s]"})
        try:
            with open(path, "rb") as f:
                img_b64 = base64.standard_b64encode(f.read()).decode()
            content.append({
                "image": {"format": "jpeg", "source": {"bytes": img_b64}}
            })
        except Exception as e:
            logger.warning(f"Frame load error {path}: {e}")

    if not any("image" in c for c in content):
        logger.error("No image frames loaded")
        return None

    audio_str = json.dumps(audio_info, ensure_ascii=False)
    content.append({"text": _PROMPT.format(srt_text=srt_text, audio_info=audio_str)})

    payload = {
        "messages": [{"role": "user", "content": content}],
        "inferenceConfig": {"maxTokens": 2000, "temperature": 0},
    }

    url = f"{BEDROCK_URL}/model/{BEDROCK_MODEL}/converse"
    result = None
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {BEDROCK_TOKEN}",
                    "Content-Type": "application/json",
                },
            )
        if resp.status_code != 200:
            logger.error(f"Bedrock {resp.status_code}: {resp.text[:400]}")
            return None
        raw = resp.json()["output"]["message"]["content"][0]["text"]
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            result = json.loads(m.group())
            result["_audio"] = audio_info   # 附加原始音频数据
            logger.info(f"Analysis done: score={result.get('overall_score')} ({os.path.basename(video_path)})")
        else:
            logger.error(f"No JSON in response: {raw[:300]}")
    except Exception as e:
        logger.error(f"analyze_clip failed: {e}")
    finally:
        for _, path, _ in frames:
            try:
                os.unlink(path)
            except Exception:
                pass
        try:
            os.rmdir(out_dir)
        except Exception:
            pass

    return result
