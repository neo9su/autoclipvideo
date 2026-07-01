"""
导演模式视频合成模块

将匹配的视频片段与TTS音频合成为最终视频
"""

import asyncio
import logging
import json
import time
from pathlib import Path
from typing import Dict, List, Optional
import tempfile
import subprocess

logger = logging.getLogger(__name__)

# ── 字幕关键词高亮（与 editor.py 同步）─────────────────────────────────────────
_DIR_HIGHLIGHT_PRODUCT: set = {
    '显白', '自然', '柔顺', '蓬松', '透气', '服帖', '轻盈', '轻薄',
    '减龄', '显年轻', '氛围感', '背影杀', '高颅顶', '小V脸', '头包脸',
    '真发', '仿真', '真人发丝', '递针', '无痕', '一梳到底',
    '不打结', '不起静电', '不脱色', '免打理', '全遮盖',
    '秒变', '变身',
}
_DIR_HIGHLIGHT_SCENE: set = {
    '通勤', '派对', '同学会', '逛街', '约会', '婚礼',
    '拍照', '聚会', '旅游', '日常', '出行', '上班', '上课',
}
_DIR_HIGHLIGHT_ACTION: set = {
    # 佩戴/安装步骤
    '分两份', '往里塞', '皮扣一勾', '防风扣', '固定好', '戴上去', '套上去',
    '扎球球', '别上去', '夹好', '梳顺', '摘下来', '取下来',
    # 造型操作
    '分缝', '拨开', '盘发', '卷发', '编发', '做造型',
    # 通用动作
    '固定', '戴上', '套上', '梳开', '夹住', '扎起',
}
_DIR_SORTED_KWS: list = sorted(
    _DIR_HIGHLIGHT_PRODUCT | _DIR_HIGHLIGHT_SCENE | _DIR_HIGHLIGHT_ACTION,
    key=len, reverse=True,
)
_WARM_GOLD = (255, 204, 0, 255)  # #FFCC00

# ASS 字幕字体名（与 GPU 服务器注册名一致）
_XQNT_FONT = "WenYue XinQingNianTi (Authorization Required) W8-J"

_DIR_ASS_HEADER = f"""\
[Script Info]
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: XQN,{_XQNT_FONT},104,&H00FFFFFF,&H000000FF,&H80141414,&H80000000,0,0,0,0,100,100,1,0,1,2,1,2,60,60,100,1
Style: KWPOP,{_XQNT_FONT},169,&H0000CCFF,&H000000FF,&H80141414,&H80000000,1,0,0,0,100,100,0,0,1,6,4,9,0,60,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

_HL_OPEN  = r"{\c&H0000CCFF&\b1}"  # warm gold
_HL_CLOSE = r"{\r}"
_B_TEXT   = r"{\3a&H80&\3c&H00141414&\bord2\shad1}"
_ANIM     = r"{\fad(120,80)\t(0,300,\fscx105\fscy105)\t(300,600,\fscx100\fscy100)}"
# 右上角弹跳动画：进入放大→回弹→稳定
_ANIM_KW_POP = (r"{\fad(0,200)"
                r"\t(0,150,\fscx130\fscy130)"
                r"\t(150,300,\fscx95\fscy95)"
                r"\t(300,450,\fscx108\fscy108)"
                r"\t(450,600,\fscx100\fscy100)}")


def _annotate_dir(text: str) -> str:
    """在 text 里标注关键词（暖金色 ASS tag）。"""
    for kw in _DIR_SORTED_KWS:
        if kw in text:
            text = text.replace(kw, _HL_OPEN + kw + _HL_CLOSE, 1)
    return text


def _sec_to_ass(s: float) -> str:
    s = max(0.0, s)
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    return f"{h}:{m:02d}:{sec:05.2f}"


# Subtitle-to-audio sync offset (seconds). Positive = subtitle appears later.
# Compensates for AAC encoder delay in the GPU concat pipeline.
_SUB_OFFSET = 0.30


def _build_director_ass(video_clips: list, transition_dur: float,
                        tts_dur_by_scene: dict = None) -> str:
    """
    根据 video_clips（含 script_text / duration）生成带关键词高亮的 ASS 字幕。
    优先使用 tts_dur_by_scene（TTS 实际时长）定时，保证字幕与语音同步。
    """
    MAX_CHARS = 14  # 每屏最多14字
    n = len(video_clips)
    cursor = _SUB_OFFSET  # apply global sync offset
    events: list = []

    for i, clip in enumerate(video_clips):
        text      = (clip.get("script_text") or "").strip()
        vid_dur   = float(clip.get("duration") or 5.0)
        scene_id  = clip.get("scene_id")
        # 优先用 TTS 实际时长，保证字幕跟语音同步；无则退化到视频片段时长
        if tts_dur_by_scene and scene_id is not None and scene_id in tts_dur_by_scene:
            duration = tts_dur_by_scene[scene_id]
        else:
            duration = vid_dur

        if not text:
            cursor += duration - (transition_dur if i < n - 1 else 0)
            continue

        # ── 逐句滚动字幕：将整段文案按标点分句，每句独立显示 ──────────────
        # 按标点切分为多个短句（逗号、句号、感叹号、问号、分号）
        import re as _re_sub
        sentences = _re_sub.split(r'(?<=[，。！？；,!?;])', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        if not sentences:
            sentences = [text]
        
        # 按字数估算每句的朗读时长（TTS 语速约 4-5 字/秒）
        total_chars = sum(len(s) for s in sentences)
        scene_dur = duration - (transition_dur if i < n - 1 else 0)
        
        sub_cursor = cursor
        for si, sentence in enumerate(sentences):
            # 按字数比例分配时长
            char_ratio = len(sentence) / max(total_chars, 1)
            sent_dur = max(1.0, scene_dur * char_ratio)  # 至少 1 秒
            
            # 每句超过 MAX_CHARS 则换行
            display = sentence
            if len(display) > MAX_CHARS:
                display = display[:MAX_CHARS] + r"\N" + display[MAX_CHARS:]
            
            ts = _sec_to_ass(sub_cursor)
            te = _sec_to_ass(sub_cursor + sent_dur)
            ann = _annotate_dir(display)
            events.append(f"Dialogue: 0,{ts},{te},XQN,,0,0,0,,{_B_TEXT}{_ANIM}{ann}")
            
            # 关键词弹出（仅第一个含高亮词的句子触发）
            if si == 0:
                kw_match = next((kw for kw in _DIR_SORTED_KWS if kw in sentence), None)
                if kw_match:
                    events.append(f"Dialogue: 1,{ts},{te},KWPOP,,0,0,0,,{_ANIM_KW_POP}{kw_match}")
            
            sub_cursor += sent_dur

        cursor += duration - (transition_dur if i < n - 1 else 0)

    return _DIR_ASS_HEADER + "\n".join(events) + "\n"


def _split_by_keywords(text: str, sorted_kws: list) -> list:
    """将文字拆成 [(片段, is_keyword), ...] 序列，长词优先匹配。"""
    result: list = []
    pos = 0
    while pos < len(text):
        matched = False
        for kw in sorted_kws:
            if text.startswith(kw, pos):
                result.append((kw, True))
                pos += len(kw)
                matched = True
                break
        if not matched:
            if result and not result[-1][1]:
                result[-1] = (result[-1][0] + text[pos], False)
            else:
                result.append((text[pos], False))
            pos += 1
    return result

class DirectorVideoComposer:
    def __init__(self, recordings_dir: str):
        self.recordings_dir = Path(recordings_dir)
        
        # 视频合成配置（对应 vibe 和传统风格）
        self.video_configs = {
            # 传统风格
            'dynamic': {
                'transition_type': 'slideright',
                'transition_duration': 0.4,
                'zoom_enabled': True,
                'text_overlay': True,
                'color_grade': 'vivid',
            },
            'smooth': {
                'transition_type': 'dissolve',
                'transition_duration': 1.0,
                'zoom_enabled': False,
                'text_overlay': True,
                'color_grade': 'natural',
            },
            'simple': {
                'transition_type': 'cut',
                'transition_duration': 0.0,
                'zoom_enabled': False,
                'text_overlay': False,
                'color_grade': 'natural',
            },
            # VibeVoice 新风格
            'trendy': {
                'transition_type': 'slideleft',
                'transition_duration': 0.4,
                'zoom_enabled': True,
                'text_overlay': True,
                'color_grade': 'vivid',
            },
            'emotional': {
                'transition_type': 'dissolve',
                'transition_duration': 0.8,
                'zoom_enabled': False,
                'text_overlay': True,
                'color_grade': 'warm',
            },
            'lifestyle': {
                'transition_type': 'slideright',
                'transition_duration': 0.5,
                'zoom_enabled': False,
                'text_overlay': True,
                'color_grade': 'natural',
            },
            'luxury': {
                'transition_type': 'dissolve',
                'transition_duration': 1.2,
                'zoom_enabled': False,
                'text_overlay': True,
                'color_grade': 'cool',
            },
            'contrast': {
                'transition_type': 'phone_zoom',
                'transition_duration': 0.6,
                'zoom_enabled': True,
                'text_overlay': True,
                'color_grade': 'vivid',
            },
        }

        # 颜色调色板（ffmpeg eq 参数）
        self._color_grades = {
            'natural':  'eq=contrast=1.05:brightness=0.02:saturation=1.05',
            'vivid':    'eq=contrast=1.1:brightness=0.05:saturation=1.2',
            'warm':     'eq=contrast=1.05:brightness=0.04:saturation=1.1,colorbalance=rs=0.05:gs=0:bs=-0.05',
            'cool':     'eq=contrast=1.08:brightness=0.02:saturation=0.95,colorbalance=rs=-0.03:gs=0:bs=0.05',
        }
        
        # 输出视频设置
        self.output_settings = {
            'width': 1080,
            'height': 1920,
            'fps': 30,
            'bitrate': '8M',
            'audio_sample_rate': 44100
        }
    
    # ── GPU service URL (mirrors editor.py) ──────────────────────────────────
    _GPU_SERVICE_URL: str = __import__('os').environ.get(
        "GPU_SERVICE_URL", "http://10.190.0.203:8877"
    )

    async def compose_final_video(self, matched_segments: List[Dict],
                                  audio_path: str,
                                  config: Dict,
                                  tts_audio_segments: Optional[List[Dict]] = None) -> Optional[str]:
        """
        合成最终视频 — 提交到 GPU 服务器 (NVENC)，本地只负责调度。
        """
        logger.info(f"[DIRECTOR] compose_final_video START: matched_segments={len(matched_segments)}, audio_path={audio_path}, tts_segs={len(tts_audio_segments) if tts_audio_segments else 0}")
        if not matched_segments:
            logger.error("[DIRECTOR] compose_final_video: matched_segments is empty")
            return None
        if not Path(audio_path).exists():
            logger.error(f"[DIRECTOR] compose_final_video: audio_path MISSING: {audio_path}")
            return None
        audio_size = Path(audio_path).stat().st_size
        logger.info(f"[DIRECTOR] compose_final_video: audio exists, size={audio_size}")

        try:
            timestamp = time.time()
            output_filename = f"director_output_{int(timestamp)}.mp4"
            output_path = self.recordings_dir / "director_outputs" / output_filename
            output_path.parent.mkdir(parents=True, exist_ok=True)

            video_style = config.get('video_style', 'dynamic')
            style_config = self.video_configs.get(video_style, self.video_configs['dynamic'])
            tr_type = style_config.get('transition_type', 'slideleft')
            tr_dur  = style_config.get('transition_duration', 0.4)

            # 0. 预计算 TTS 时长映射（后续多步骤都需要）
            tts_dur_by_scene: Dict[int, float] = {}
            if tts_audio_segments:
                for seg in tts_audio_segments:
                    sid = seg.get("scene_id")
                    dur = seg.get("duration", 0.0)
                    if sid is not None and dur > 0:
                        tts_dur_by_scene[sid] = dur
            logger.info(f"TTS duration map: {tts_dur_by_scene} (total={sum(tts_dur_by_scene.values()):.1f}s)")

            # 1. 准备片段元数据（含 room_id），用 TTS 时长对齐 video clip duration
            video_clips = await self._prepare_video_clips(matched_segments, config, tts_dur_by_scene)
            logger.info(f"[DIRECTOR] compose_final_video: prepared {len(video_clips) if video_clips else 0} video_clips")
            if not video_clips:
                logger.error("[DIRECTOR] compose_final_video: video_clips is EMPTY after preparation")
                return None
            for i, vc in enumerate(video_clips):
                logger.info(f"[DIRECTOR] compose_final_video clip[{i}]: file_path={vc.get('file_path','?')} room_id={vc.get('room_id')} filename={vc.get('filename')} start={vc.get('start_time')} dur={vc.get('duration')} scene_id={vc.get('scene_id')}")
                fp = vc.get('file_path', '')
                if fp:
                    logger.info(f"[DIRECTOR] compose_final_video clip[{i}]: local file exists={Path(fp).exists()} size={Path(fp).stat().st_size if Path(fp).exists() else '?'}")

            # 2. 同步源文件到 GPU（遇到未同步的文件才上传）
            await self._ensure_clips_on_gpu(video_clips)

            # 3. 构建 ASS 字幕（本地生成，含关键词高亮）
            # video clip duration 已对齐 TTS，字幕用同一个 tts_dur_by_scene 保证同步
            ass_content = _build_director_ass(video_clips, tr_dur, tts_dur_by_scene)

            # 4. 读取 TTS 音频 → base64
            import base64 as _b64
            tts_b64 = ""
            try:
                import subprocess as _sp
                clean_wav = audio_path + "_clean.wav"
                _sp.run(
                    ["ffmpeg", "-y", "-i", audio_path, "-c:a", "pcm_s16le",
                     "-ar", "44100", clean_wav],
                    capture_output=True,
                )
                audio_source = clean_wav if Path(clean_wav).exists() and Path(clean_wav).stat().st_size > 0 else audio_path
                logger.info(f"[DIRECTOR] compose_final_video: audio_source={audio_source} size={Path(audio_source).stat().st_size}")
                with open(audio_source, "rb") as f:
                    raw = f.read()
                if Path(clean_wav).exists() and Path(clean_wav).stat().st_size > 0:
                    Path(clean_wav).unlink(missing_ok=True)
                tts_b64 = _b64.b64encode(raw).decode()
                logger.info(f"[DIRECTOR] compose_final_video: tts_b64 encoded, len={len(tts_b64)}")
            except Exception as ae:
                logger.error(f"[DIRECTOR] compose_final_video: TTS audio encode FAILED: {ae}")
                return None

            # 5. 提交 GPU director job
            import aiohttp as _aio_dv
            clips_payload = [
                {
                    "room_id":   c["room_id"],
                    "filename":  c["filename"],
                    "start":     c["start_time"],
                    "duration":  c["duration"],
                    "scene_type": c.get("scene_type", ""),
                }
                for c in video_clips
            ]
            # 计算总 TTS 时长，传给 GPU 用 -t 精确控制输出时长（替代 -shortest）
            total_tts_duration = sum(tts_dur_by_scene.values()) if tts_dur_by_scene else 0.0

            payload = {
                "clips": clips_payload,
                "ass_content": ass_content,
                "tts_audio_b64": tts_b64,
                "transition_type": tr_type,
                "transition_duration": tr_dur,
                "thumb_seek": 3.0,
                "total_tts_duration": total_tts_duration,
            }

            logger.info(f"[DIRECTOR] compose_final_video: submitting to {self._GPU_SERVICE_URL}/director-jobs, clips={len(clips_payload)}, ass_len={len(ass_content)}, tts_b64_len={len(tts_b64)}, total_tts_dur={total_tts_duration:.1f}s")
            # Retry GPU submission on transient connection errors
            _resp_status = None
            _resp_text = ""
            job_id = None
            for _retry in range(3):
                try:
                    async with _aio_dv.ClientSession() as session:
                        async with session.post(
                            f"{self._GPU_SERVICE_URL}/director-jobs", json=payload,
                            timeout=_aio_dv.ClientTimeout(total=30),
                        ) as resp:
                            _resp_status = resp.status
                            _resp_text = await resp.text()
                    if _resp_status == 201:
                        import json as _json_dv
                        job_id = _json_dv.loads(_resp_text)["job_id"]
                        logger.info(f"[DIRECTOR] compose_final_video: GPU job queued: {job_id}")
                        break
                    elif _resp_status >= 500:
                        logger.warning(f"[DIRECTOR] compose_final_video: GPU returned {_resp_status}, retry {_retry+1}/3")
                        await asyncio.sleep(5 * (_retry + 1))
                    else:
                        logger.error(f"[DIRECTOR] compose_final_video: GPU submit FAILED status={_resp_status} error={_resp_text[:500]}")
                        return None
                except (_aio_dv.ClientConnectorError, _aio_dv.ClientOSError, _aio_dv.ServerDisconnectedError) as ce:
                    logger.warning(f"[DIRECTOR] compose_final_video: GPU connection error, retry {_retry+1}/3: {ce}")
                    await asyncio.sleep(5 * (_retry + 1))
                except Exception as re:
                    logger.error(f"[DIRECTOR] compose_final_video: unexpected error submitting GPU job: {re}")
                    return None
            if job_id is None:
                logger.error(f"[DIRECTOR] compose_final_video: GPU job submit failed after 3 retries: status={_resp_status} text={_resp_text[:500]}")
                return None

            # 6. 轮询（最多 5 分钟，GPU 队列卡住时快速 fallback 到本地 ffmpeg）
            deadline = time.time() + 300
            stuck_count = 0  # consecutive polls still "queued"
            consecutive_none = 0  # consecutive polls returning status=None (job disappeared)
            poll_count = 0
            while time.time() < deadline:
                await asyncio.sleep(6)
                poll_count += 1
                try:
                    async with _aio_dv.ClientSession() as session:
                        async with session.get(
                            f"{self._GPU_SERVICE_URL}/director-jobs/{job_id}",
                            timeout=_aio_dv.ClientTimeout(total=15),
                        ) as r:
                            if r.status == 404:
                                # Job disappeared — GPU service likely restarted
                                logger.warning(f"[DIRECTOR] compose_final_video job {job_id} disappeared (404) — falling back to local ffmpeg")
                                return await self._compose_with_ffmpeg(
                                    video_clips, audio_path, str(output_path), style_config, config
                                )
                            data = await r.json()
                except Exception as pe:
                    logger.warning(f"[DIRECTOR] compose_final_video poll error #{poll_count}: {pe}")
                    continue
                status = data.get("status")
                phase  = data.get("phase", "")
                pct    = data.get("pct", 0)
                if poll_count % 5 == 0 or status in ("error", "done"):
                    logger.info(f"[DIRECTOR] compose_final_video job {job_id}: status={status} phase={phase} pct={pct}%")
                if status == "done":
                    logger.info(f"[DIRECTOR] compose_final_video job {job_id} DONE after {poll_count} polls")
                    break
                if status == "error":
                    logger.warning(f"[DIRECTOR] compose_final_video job {job_id} ERROR: {data.get('error')} — falling back to local ffmpeg")
                    return await self._compose_with_ffmpeg(
                        video_clips, audio_path, str(output_path), style_config, config
                    )
                # Detect job disappearance: status=None means GPU service restarted and lost the job
                if status is None:
                    consecutive_none += 1
                    if consecutive_none >= 2:
                        logger.warning(f"[DIRECTOR] compose_final_video job {job_id} vanished (status=None x{consecutive_none}) — GPU service restarted, falling back to local ffmpeg")
                        return await self._compose_with_ffmpeg(
                            video_clips, audio_path, str(output_path), style_config, config
                        )
                else:
                    consecutive_none = 0  # reset counter on valid status
                # 检测队列卡死：超过 3 分钟仍 queued → 主动 fallback
                if status == "queued" and poll_count >= 10:
                    stuck_count += 1
                    if stuck_count >= 1:
                        logger.warning(f"[DIRECTOR] compose_final_video job {job_id} stuck in queued for ~{poll_count*6:.0f}s — falling back to local ffmpeg")
                        return await self._compose_with_ffmpeg(
                            video_clips, audio_path, str(output_path), style_config, config
                        )
            else:
                logger.warning(f"[DIRECTOR] compose_final_video job {job_id} TIMED OUT — falling back to local ffmpeg")
                return await self._compose_with_ffmpeg(
                    video_clips, audio_path, str(output_path), style_config, config
                )

            # 7. 下载结果
            logger.info(f"[DIRECTOR] compose_final_video: downloading job {job_id} mp4")
            async with _aio_dv.ClientSession() as session:
                async with session.get(
                    f"{self._GPU_SERVICE_URL}/director-jobs/{job_id}/mp4",
                    timeout=_aio_dv.ClientTimeout(total=300),
                ) as r:
                    if r.status != 200:
                        err_text = await r.text()
                        logger.warning(f"[DIRECTOR] compose_final_video download failed (status={r.status}) — falling back to local ffmpeg")
                        return await self._compose_with_ffmpeg(
                            video_clips, audio_path, str(output_path), style_config, config
                        )
                    _content = await r.read()
                    logger.info(f"[DIRECTOR] compose_final_video: downloaded {len(_content)} bytes")
            with open(str(output_path), "wb") as f:
                f.write(_content)
            if not output_path.exists() or output_path.stat().st_size == 0:
                logger.warning(f"[DIRECTOR] compose_final_video: output empty — falling back to local ffmpeg")
                return await self._compose_with_ffmpeg(
                    video_clips, audio_path, str(output_path), style_config, config
                )
            logger.info(f"[DIRECTOR] compose_final_video: output file size={output_path.stat().st_size}")

            logger.info(f"Director video composition complete (GPU): {output_path}")

            # 8. 封面（anime 风格）
            try:
                from thumbnail import generate_thumbnail as _gen_thumb
                title    = config.get('wig_model', '') or '假发变美'
                subtitle = config.get('wig_color', '') or '点击查看同款'
                await _gen_thumb(str(output_path), title=title[:8], subtitle=subtitle[:12])
            except Exception as te:
                logger.warning(f"Thumbnail failed: {te}")

            return str(output_path)

        except Exception as e:
            logger.error(f"[DIRECTOR] compose_final_video UNHANDLED ERROR: {e}", exc_info=True)
            return None

    async def _ensure_clips_on_gpu(self, video_clips: List[Dict]) -> None:
        """确保所有源文件都在 GPU 服务器上；缺少的文件通过 sync.py 上传。"""
        import aiohttp as _aio_ensure
        for clip in video_clips:
            room_id  = clip.get("room_id")
            filename = clip.get("filename")
            if not room_id or not filename:
                continue
            local_path = clip.get("file_path", "")
            if not local_path or not Path(local_path).exists():
                logger.warning(f"Local file missing for sync: {local_path}")
                continue
            # 检测 GPU 上是否有该文件（POST 一个探测 clip-job）
            try:
                async with _aio_ensure.ClientSession() as session:
                    async with session.post(
                        f"{self._GPU_SERVICE_URL}/clip-jobs",
                        json={
                            "mp4_filename": filename,
                            "room_id": room_id,
                            "segments": [{"start": 0, "end": 1}],
                            "ass_content": "",
                            "thumb_seek": 0.5,
                        },
                        timeout=_aio_ensure.ClientTimeout(total=10),
                    ) as probe:
                        probe_status = probe.status
                if probe_status == 201:
                    pass  # 文件存在
                elif probe_status == 404:
                    logger.info(f"Syncing {filename} to GPU...")
                    from sync import sync_file
                    await sync_file(local_path, room_id)
            except Exception as se:
                logger.warning(f"GPU file check/sync failed for {filename}: {se}")
    
    async def _prepare_video_clips(self, matched_segments: List[Dict], 
                                 config: Dict,
                                 tts_dur_by_scene: Optional[Dict[int, float]] = None) -> List[Dict]:
        """准备视频片段信息。
        
        核心改进：video clip duration 以 TTS 实际时长为准，确保视频和语音天然对齐。
        连续匹配到同一录像且时间衔接的场景合并为一个长片段，避免讲解中途切断。
        """
        if tts_dur_by_scene is None:
            tts_dur_by_scene = {}
        raw_clips = []
        
        for i, segment_data in enumerate(matched_segments):
            recording_id = segment_data.get('matched_recording_id')
            if not recording_id:
                continue
            
            # 查找录像文件（含 room_id、filename）
            rec_info = await self._find_recording_file(recording_id)
            if not rec_info:
                logger.warning(f"Recording file not found for ID {recording_id}")
                continue
            video_file = rec_info["path"]

            seg = segment_data.get('script_segment', {})
            clip_info = {
                'index': i,
                'file_path': video_file,
                'room_id': rec_info["room_id"],
                'filename': rec_info["filename"],
                'rec_duration': segment_data.get('matched_rec_duration', 600.0),
                'start_time': segment_data.get('matched_start_time', 0.0),
                'duration': segment_data.get('matched_duration', 15.0),
                # voiceover_text 优先，兼容 text 字段
                'script_text': seg.get('voiceover_text', '') or seg.get('text', ''),
                'scene_type': seg.get('scene_type', ''),
                'scene_id': seg.get('scene_id'),
                'confidence': segment_data.get('confidence_score', 0.0),
            }
            
            raw_clips.append(clip_info)
        
        # ── TTS 时长对齐：video clip duration 以 TTS 实际时长为准 ──────────────────
        # 这样确保每段视频的长度精确匹配配音时长，不会出现音视频不同步
        for clip in raw_clips:
            scene_id = clip.get('scene_id')
            if scene_id is not None and scene_id in tts_dur_by_scene:
                tts_dur = tts_dur_by_scene[scene_id]
                matched_dur = clip['duration']
                start_time = clip['start_time']
                rec_dur = clip.get('rec_duration', 600.0)
                # TTS 时长作为视频片段目标时长
                clip['duration'] = tts_dur
                # 边界检查：如果 start + tts_dur 超过录像时长，向前调整 start_time
                if start_time + tts_dur > rec_dur:
                    new_start = max(0.0, rec_dur - tts_dur)
                    logger.info(f"Clip {clip['index']} scene {scene_id}: "
                               f"start {start_time:.1f}s→{new_start:.1f}s "
                               f"(录像{rec_dur:.0f}s, TTS需{tts_dur:.1f}s)")
                    clip['start_time'] = new_start
                logger.debug(f"Clip {clip['index']} scene {scene_id}: "
                           f"duration {matched_dur:.1f}s → {clip['duration']:.1f}s (TTS={tts_dur:.1f}s)")
        
        # Merge consecutive clips from the same recording file where times are adjacent
        video_clips = []
        for clip in raw_clips:
            if (video_clips
                and clip['filename'] == video_clips[-1]['filename']
                and abs(clip['start_time'] - (video_clips[-1]['start_time'] + video_clips[-1]['duration'])) < 1.0):
                # Merge: extend previous clip duration, concatenate script text
                prev = video_clips[-1]
                prev['duration'] = (clip['start_time'] + clip['duration']) - prev['start_time']
                prev['script_text'] = (prev['script_text'] + ' ' + clip['script_text']).strip()
                # 跟踪合并的 scene_ids，用于字幕时长计算
                if clip.get('scene_id') is not None:
                    if 'merged_scene_ids' not in prev:
                        prev['merged_scene_ids'] = [prev.get('scene_id')]
                    prev['merged_scene_ids'].append(clip['scene_id'])
                # 合并后的总 TTS 时长 = 各 scene 的 TTS 时长之和
                merged_ids = prev.get('merged_scene_ids', [prev.get('scene_id')])
                merged_tts_total = sum(tts_dur_by_scene.get(sid, 0) for sid in merged_ids if sid is not None)
                if merged_tts_total > 0:
                    prev['duration'] = min(merged_tts_total, prev['duration'])
                logger.info(f"Merged clip {clip['index']} into previous (same recording, continuous)")
            else:
                video_clips.append(clip)
        
        # Re-index after merge
        for i, c in enumerate(video_clips):
            c['index'] = i
        
        logger.info(f"Prepared {len(video_clips)} video clips (merged from {len(raw_clips)} segments)")
        for c in video_clips:
            logger.info(f"  clip {c['index']}: scene={c.get('scene_id')} dur={c['duration']:.1f}s start={c['start_time']:.1f}s")
        return video_clips
    
    async def _find_recording_file(self, recording_id: int) -> Optional[Dict]:
        """查找录像原始文件路径，返回 {path, room_id, filename} 或 None。"""
        import aiosqlite
        from db import DB_PATH, aio_connect

        try:
            async with aio_connect() as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT filename, room_id FROM recordings WHERE id = ?",
                    (recording_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                if row:
                    p = self.recordings_dir / row["filename"]
                    exists = p.exists()
                    if not exists:
                        logger.warning(f"[DIRECTOR] _find_recording_file: recording_id={recording_id} file={row['filename']} DOES NOT EXIST at {p}")
                        # Try checking alternative paths
                        alt = Path(row["filename"])
                        if alt.exists():
                            logger.info(f"[DIRECTOR] _find_recording_file: found at relative path {alt}")
                            p = alt
                            exists = True
                    if exists:
                        logger.info(f"[DIRECTOR] _find_recording_file: recording_id={recording_id} file={row['filename']} room_id={row['room_id']} path={p}")
                        return {
                            "path": str(p),
                            "room_id": row["room_id"],
                            "filename": row["filename"],
                        }
                else:
                    logger.warning(f"[DIRECTOR] _find_recording_file: recording_id={recording_id} NOT FOUND in DB")

        except Exception as e:
            logger.warning(f"[DIRECTOR] _find_recording_file: failed for ID {recording_id}: {e}")

        return None
    
    async def _compose_with_ffmpeg(self, video_clips: List[Dict], 
                                 audio_path: str, output_path: str,
                                 style_config: Dict, config: Dict) -> Optional[str]:
        """使用FFmpeg合成视频 — 返回输出路径或 None。"""
        try:
            # 创建临时目录
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                
                # 第一步：并行处理每个视频片段（VideoToolbox 支持多路并发编码）
                _enc_sem = asyncio.Semaphore(2)  # 最多2路并发，避免VideoToolbox超限

                async def _process_with_sem(clip):
                    async with _enc_sem:
                        return await self._process_single_clip(clip, temp_path, style_config, config)

                results = await asyncio.gather(*[_process_with_sem(c) for c in video_clips])
                # Preserve order; filter out failed clips
                processed_clips = [r for r in results if r is not None]

                if not processed_clips:
                    logger.error("No clips were successfully processed")
                    return None
                
                # 第二步：转场合并
                tr_type = style_config.get('transition_type', 'slideleft')
                tr_dur  = style_config.get('transition_duration', 0.4)

                if tr_type == 'cut' or len(processed_clips) == 1:
                    # Hard-cut: stream-copy concat
                    concat_file = temp_path / "concat_list.txt"
                    await self._create_concat_file(processed_clips, concat_file)
                    merged_video = await self._concat_clips(str(concat_file), temp_path)
                elif tr_type == 'phone_zoom':
                    # 手机放大转场（逐对合并）
                    merged_video = await self._phone_zoom_merge_all(processed_clips, temp_path)
                else:
                    # FFmpeg xfade 转场链（支持 slideleft/slideright/fade/dissolve 等）
                    clip_durs = [await self._get_audio_duration(f) for f in processed_clips]
                    logger.info(f"Clip durations: {list(zip([Path(f).name for f in processed_clips], clip_durs))}")
                    # 探测失败（0.0）时用实际时长估算，避免偏移计算错误
                    if any(d <= 0 for d in clip_durs):
                        logger.warning("Some clip durations failed to probe — falling back to concat")
                        concat_file = temp_path / "concat_fallback.txt"
                        await self._create_concat_file(processed_clips, concat_file)
                        merged_video = await self._concat_clips(str(concat_file), temp_path)
                    else:
                        merged_video = await self._xfade_merge(
                            processed_clips, clip_durs, tr_type, tr_dur, temp_path
                        )
                        if not merged_video:
                            # xfade 失败时 fallback 到 concat
                            logger.warning("xfade failed — falling back to concat")
                            concat_file = temp_path / "concat_fallback.txt"
                            await self._create_concat_file(processed_clips, concat_file)
                            merged_video = await self._concat_clips(str(concat_file), temp_path)

                if not merged_video or not Path(merged_video).exists():
                    logger.error("Clip merge failed")
                    return None

                # 第三步：合并音频
                ok = await self._final_composition(
                    merged_video, audio_path, output_path, style_config
                )
                return output_path if ok else None
        
        except Exception as e:
            logger.error(f"FFmpeg composition failed: {e}")
            return None
    
    async def _process_single_clip(self, clip: Dict, temp_dir: Path,
                                 style_config: Dict, config: Dict) -> Optional[str]:
        """处理单个视频片段，含字幕叠加（PNG overlay，上紫下绿渐变描边）"""
        import os
        try:
            input_file = clip['file_path']
            start_time = clip['start_time']
            duration   = clip['duration']
            # Clamp start_time to source file bounds to prevent empty output
            src_dur = await self._get_audio_duration(input_file)
            if src_dur > 0 and start_time >= src_dur:
                start_time = max(0.0, src_dur - duration)
                logger.info(f"Clip {clip['index']}: clamped start {clip['start_time']} → {start_time:.1f} (src_dur={src_dur:.1f})")
            duration = min(duration, max(1.0, src_dur - start_time)) if src_dur > 0 else duration
            logger.info(f"Processing clip {clip['index']}: {Path(input_file).name} ss={start_time} t={duration}")

            output_file = temp_dir / f"clip_{clip['index']:03d}.mp4"
            vf_base     = self._build_video_filter(style_config, config)

            subtitle_text = (clip.get('script_text', '') or '').strip() if style_config.get('text_overlay', False) else ''

            if subtitle_text:
                is_highlight = clip.get('scene_type', '') in self._HIGHLIGHT_SCENE_TYPES
                CHARS_PER_FRAME = 10 if is_highlight else 12
                # 将文字分成每帧12字的滚动块
                chunks = [subtitle_text[i:i+CHARS_PER_FRAME]
                          for i in range(0, len(subtitle_text), CHARS_PER_FRAME)]
                chunk_dur = duration / max(len(chunks), 1)
                logger.info(f"Clip {clip['index']}: subtitle {len(chunks)} chunks, chunk_dur={chunk_dur:.2f}s, highlight={is_highlight}")

                loop = asyncio.get_running_loop()
                # 为每个文字块生成 PNG
                chunk_pngs = []
                for ci, chunk in enumerate(chunks):
                    png_path = str(temp_dir / f"sub_{clip['index']:03d}_{ci:02d}.png")
                    ok = await loop.run_in_executor(
                        None, self._make_subtitle_png, chunk, png_path, is_highlight
                    )
                    if ok and os.path.exists(png_path):
                        chunk_pngs.append(png_path)
                    else:
                        logger.warning(f"Subtitle PNG failed for clip {clip['index']} chunk {ci}: {chunk!r}")
                        chunk_pngs.append(None)

                valid_pngs = [(i, p) for i, p in enumerate(chunk_pngs) if p]
                if valid_pngs:
                    # 构建 ffmpeg 命令：主视频 + 每个字幕PNG输入
                    extra_inputs = []
                    for _, p in valid_pngs:
                        extra_inputs += ['-loop', '1', '-t', str(duration), '-i', p]

                    # filter_complex：不加 fade（fade 从 PTS=0 算，会导致 chunk1+ 在激活时已透明）
                    # 直接用 enable 时间窗实现切换
                    parts = [f'[0:v]{vf_base}[base]']
                    prev = 'base'
                    for idx, (ci, _) in enumerate(valid_pngs):
                        t0 = ci * chunk_dur
                        t1 = min((ci + 1) * chunk_dur, duration)
                        inp_idx = idx + 1
                        is_last = (idx == len(valid_pngs) - 1)
                        o_lbl = 'out' if is_last else f'v{idx}'
                        if is_highlight:
                            ov = (f'[{prev}][{inp_idx}:v]overlay='
                                  f'x=(W-overlay_w)/2:'
                                  f'y=H-280-overlay_h+sin(t*8)*15:eval=frame:'
                                  f"enable='between(t\\,{t0:.3f}\\,{t1:.3f})':format=auto[{o_lbl}]")
                        else:
                            ov = (f'[{prev}][{inp_idx}:v]overlay=0:0:'
                                  f"enable='between(t\\,{t0:.3f}\\,{t1:.3f})':format=auto[{o_lbl}]")
                        parts.append(ov)
                        prev = o_lbl

                    fc = ';'.join(parts)
                    cmd = [
                        'ffmpeg', '-y',
                        '-ss', str(start_time), '-t', str(duration), '-i', input_file,
                        *extra_inputs,
                        '-filter_complex', fc,
                        '-map', '[out]',
                        '-c:v', 'h264_videotoolbox', '-b:v', '8M', '-allow_sw', '1',
                        '-r', str(self.output_settings['fps']),
                        '-an', str(output_file),
                    ]
                else:
                    subtitle_text = ''  # fall through to no-subtitle path

            if not subtitle_text:
                cmd = [
                    'ffmpeg', '-y',
                    '-ss', str(start_time), '-t', str(duration), '-i', input_file,
                    '-vf', vf_base,
                    '-c:v', 'h264_videotoolbox', '-b:v', '8M', '-allow_sw', '1',
                    '-s', f"{self.output_settings['width']}x{self.output_settings['height']}",
                    '-r', str(self.output_settings['fps']),
                    '-an', str(output_file),
                ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            fsize = output_file.stat().st_size if output_file.exists() else 0
            if process.returncode == 0 and fsize > 1000:
                return str(output_file)
            else:
                logger.warning(f"Clip {clip['index']} processing failed (rc={process.returncode}, size={fsize}): {stderr.decode()[-400:]}")
                return None

        except Exception as e:
            logger.error(f"Error processing clip {clip['index']}: {e}")
            return None

    # 高光场景类型 — 使用2倍字号+跳动动画
    _HIGHLIGHT_SCENE_TYPES = {'hook', 'transformation', 'cta', 'promotion', 'urgency'}

    def _make_subtitle_png(self, text: str, out_png: str, highlight: bool = False) -> bool:
        """
        生成字幕 PNG（透明背景，文悦新青年体，上紫下绿渐变描边）。

        普通场景：108px，全帧PNG（1080×1920），文字预置于底部
        高光场景：216px（2倍），紧凑裁剪PNG（文字区域+边距），
                  调用方使用 overlay 动画定位实现跳动效果
        """
        import os
        try:
            from PIL import Image, ImageDraw, ImageFont
            import numpy as np

            W = self.output_settings['width']   # 1080
            H = self.output_settings['height']  # 1920
            # 字幕参数
            # 普通场景：52px，每行12字，最多2行，底部字幕栏
            # 高光场景：104px（2倍），每行10字，最多2行，紧凑PNG+跳动动画
            font_size = 80 if highlight else 60
            stroke_w  = 6  if highlight else 4

            _assets = os.path.join(os.path.dirname(__file__), "assets", "fonts")
            font_path_primary = os.path.join(_assets, "WenYue-XinQingNianTi-W8-J-2.otf")
            font_paths = [
                font_path_primary,
                os.path.join(_assets, "ZCOOLQingKeHuangYou.ttf"),
                os.path.join(_assets, "ZCOOLKuaiLe-Regular.ttf"),
                "/System/Library/Fonts/STHeiti Medium.ttc",
                "/System/Library/Fonts/Hiragino Sans GB.ttc",
                "/System/Library/Fonts/PingFang.ttc",
                "C:/Windows/Fonts/msyh.ttc",
                "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            ]
            font = None
            for fp in font_paths:
                if os.path.exists(fp):
                    try:
                        f = ImageFont.truetype(fp, font_size)
                        bbox = f.getbbox("中文")
                        if bbox[2] - bbox[0] > font_size * 0.5:
                            font = f
                            break
                    except Exception:
                        pass
            if font is None:
                logger.warning("No CJK font found, subtitle will use default (small) font")
                font = ImageFont.load_default()

            # 每行最多字数（12字/行，普通；10字/行，高光）
            MAX_CHARS_PER_LINE = 10 if highlight else 12
            MAX_LINES = 2  # 最多2行，超出截断
            # 分行：每行 MAX_CHARS_PER_LINE 字
            raw_lines = [text[i:i+MAX_CHARS_PER_LINE]
                         for i in range(0, len(text), MAX_CHARS_PER_LINE)]
            # 最多2行，超出在第2行末尾加省略号
            if len(raw_lines) > MAX_LINES:
                lines = raw_lines[:MAX_LINES]
                lines[-1] = lines[-1][:MAX_CHARS_PER_LINE-1] + '…'
            else:
                lines = raw_lines if raw_lines else [text]

            line_h = font_size + 10

            # 计算文字区域尺寸
            max_w = 0
            for line in lines:
                try:
                    bb = font.getbbox(line)
                    max_w = max(max_w, bb[2] - bb[0])
                except Exception:
                    max_w = max(max_w, font_size * len(line))
            total_h = len(lines) * line_h

            if highlight:
                # 高光：紧凑PNG，用于 overlay 动画定位
                PAD = stroke_w + 8
                IMG_W = min(W, max_w + 2 * (stroke_w + 20))
                IMG_H = total_h + 2 * PAD
                canvas_w, canvas_h = IMG_W, IMG_H
                y_start = PAD
            else:
                # 普通：全帧PNG，字幕栏在底部（距底 80px）
                canvas_w, canvas_h = W, H
                y_start = H - 80 - total_h

            purple = (160,  0, 255, 255)
            green  = (  0, 220,  80, 255)

            def _render_layer(stroke_color: tuple) -> Image.Image:
                layer = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
                d = ImageDraw.Draw(layer)
                for i, line in enumerate(lines):
                    try:
                        bb = font.getbbox(line)
                        tx = (canvas_w - (bb[2] - bb[0])) // 2 - bb[0]
                        ty = y_start + i * line_h - bb[1]
                    except Exception:
                        tx, ty = 0, y_start + i * line_h
                    d.text((tx, ty), line, font=font,
                           fill=(255, 255, 255, 255),
                           stroke_width=stroke_w, stroke_fill=stroke_color)
                return layer

            layer_p = _render_layer(purple)
            layer_g = _render_layer(green)

            # 垂直渐变蒙版：上255(紫) → 下0(绿)
            mask_arr = np.zeros((canvas_h, canvas_w), dtype=np.uint8)
            y0 = max(0, y_start - stroke_w)
            y1 = min(canvas_h, y_start + total_h + stroke_w)
            h_range = max(y1 - y0, 1)
            ys = np.arange(y0, y1)
            vals = np.clip((255 * (1.0 - (ys - y0) / h_range)).astype(np.uint8), 0, 255)
            mask_arr[y0:y1, :] = vals[:, None]
            mask = Image.fromarray(mask_arr, 'L')

            blended = Image.composite(layer_p, layer_g, mask)

            # ── 关键词金色叠加层 ────────────────────────────────────────────────
            # 在渐变描边白字的基础上，将关键词片段覆盖为暖金色（#FFCC00）
            kw_layer = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
            kd = ImageDraw.Draw(kw_layer)
            for i, line in enumerate(lines):
                segs = _split_by_keywords(line, _DIR_SORTED_KWS)
                if not any(is_kw for _, is_kw in segs):
                    continue
                try:
                    bb_full = font.getbbox(line)
                    line_visual_left = (canvas_w - (bb_full[2] - bb_full[0])) // 2
                    ty_kw = y_start + i * line_h - bb_full[1]
                except Exception:
                    line_visual_left = 0
                    ty_kw = y_start + i * line_h
                char_pos = 0
                for seg_text, is_kw in segs:
                    if is_kw and seg_text:
                        try:
                            prefix = line[:char_pos]
                            try:
                                prefix_adv = int(font.getlength(prefix)) if prefix else 0
                            except AttributeError:
                                prefix_adv = int(font.getbbox(prefix)[2] - font.getbbox(prefix)[0]) if prefix else 0
                            kw_bb = font.getbbox(seg_text)
                            kw_x = line_visual_left + prefix_adv - kw_bb[0]
                            kd.text((kw_x, ty_kw), seg_text, font=font,
                                    fill=_WARM_GOLD, stroke_width=0)
                        except Exception as ke:
                            logger.debug(f"Keyword gold overlay error: {ke}")
                    char_pos += len(seg_text)

            blended = Image.alpha_composite(blended, kw_layer)
            blended.save(out_png, "PNG")
            return True
        except Exception as e:
            logger.warning(f"Subtitle PNG failed: {e}")
            return False
    
    def _build_video_filter(self, style_config: Dict, config: Dict) -> str:
        """构建视频滤镜字符串（输出统一为 yuv420p + fps=30，保证 xfade 兼容性）"""
        filters = []

        # 基础缩放和裁剪
        filters.append(
            f"scale={self.output_settings['width']}:{self.output_settings['height']}"
            ":force_original_aspect_ratio=increase:flags=lanczos"
        )
        filters.append(f"crop={self.output_settings['width']}:{self.output_settings['height']}")

        # 轻微加速（zoom 风格，不用 zoompan 避免极慢）
        if style_config.get('zoom_enabled', False):
            filters.append("setpts=0.95*PTS")

        # 颜色调色
        grade_key = style_config.get('color_grade', 'vivid')
        filters.append(self._color_grades.get(grade_key, self._color_grades['vivid']))

        # 统一像素格式 + 帧率（xfade 要求两路输入格式完全一致）
        filters.append(f"fps={self.output_settings['fps']}")
        filters.append("format=yuv420p")

        return ','.join(filters)
    
    async def _create_concat_file(self, processed_clips: List[str],
                                concat_file: Path) -> None:
        """创建ffmpeg concat文件"""
        with open(concat_file, 'w', encoding='utf-8') as f:
            for clip_file in processed_clips:
                f.write(f"file '{clip_file}'\n")

    async def _concat_clips(self, concat_file: str, temp_dir: Path) -> Optional[str]:
        """Stream-copy concat — used for cut/single-clip cases."""
        out = str(temp_dir / "merged_concat.mp4")
        proc = await asyncio.create_subprocess_exec(
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_file,
            '-c', 'copy', out,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()
        return out if Path(out).exists() else None

    # ── Phone-zoom transition ─────────────────────────────────────────────────

    @staticmethod
    def _build_phone_still(frame_b_path: str, out_path: str, W: int, H: int) -> bool:
        """
        将下一片段首帧合成到仿 iPhone 边框内，背景为模糊底图。
        移植自 editor.py（经典模式同款 phone_zoom 转场）。
        """
        import os
        try:
            from PIL import Image, ImageFilter, ImageDraw
            b_img = Image.open(frame_b_path).convert("RGB").resize((W, H), Image.LANCZOS)

            bg    = b_img.filter(ImageFilter.GaussianBlur(radius=22))
            dark  = Image.new("RGBA", (W, H), (0, 0, 0, 90))
            canvas = bg.convert("RGBA")
            canvas.paste(dark, mask=dark)

            PH_W   = int(W * 0.76)
            PH_H   = min(int(PH_W * H / W * 1.04), int(H * 0.87))
            BEZEL  = max(12, int(PH_W * 0.042))
            CORNER = int(PH_W * 0.105)
            SCR_W  = PH_W - 2 * BEZEL
            SCR_H  = PH_H - 2 * BEZEL

            phone = Image.new("RGBA", (PH_W, PH_H), (0, 0, 0, 0))
            draw  = ImageDraw.Draw(phone)
            draw.rounded_rectangle([0, 0, PH_W - 1, PH_H - 1], radius=CORNER, fill=(18, 18, 20, 255))

            SCR_CORNER = int(CORNER * 0.65)
            draw.rounded_rectangle([BEZEL, BEZEL, BEZEL + SCR_W - 1, BEZEL + SCR_H - 1],
                                   radius=SCR_CORNER, fill=(0, 0, 0, 255))
            b_scr = b_img.resize((SCR_W, SCR_H), Image.LANCZOS)
            mask  = Image.new("L", (SCR_W, SCR_H), 0)
            ImageDraw.Draw(mask).rounded_rectangle([0, 0, SCR_W - 1, SCR_H - 1],
                                                   radius=SCR_CORNER, fill=255)
            phone.paste(b_scr.convert("RGBA"), (BEZEL, BEZEL), mask)

            NIL_W = int(PH_W * 0.28)
            NIL_H = int(BEZEL * 1.1)
            NIL_X = (PH_W - NIL_W) // 2
            NIL_Y = BEZEL - NIL_H + 3
            draw.rounded_rectangle([NIL_X, NIL_Y, NIL_X + NIL_W, NIL_Y + NIL_H],
                                   radius=NIL_H // 2, fill=(10, 10, 12, 240))
            draw.line([(CORNER, 1), (PH_W - CORNER, 1)], fill=(80, 80, 85, 160), width=1)

            canvas.paste(phone, ((W - PH_W) // 2, (H - PH_H) // 2), phone)
            canvas.convert("RGB").save(out_path, "JPEG", quality=94)
            return True
        except Exception as exc:
            logger.error(f"_build_phone_still: {exc}")
            return False

    async def _phone_zoom_merge(self, f1: str, f2: str, dst: str) -> bool:
        """
        手机放大转场：在两段视频之间插入 0.6s 的 iPhone 手机屏幕放大动画。
        f1/f2 为无音频的视频片段。
        """
        import os
        W = self.output_settings['width']
        H = self.output_settings['height']
        ANIM_DUR  = 0.6
        FADE_DUR  = 0.2

        frame_b = dst + "_pz_b.jpg"
        still   = dst + "_pz_still.jpg"
        anim    = dst + "_pz_anim.mp4"
        tmp1    = dst + "_pz_s1.mp4"

        async def _cleanup():
            for p in (frame_b, still, anim, tmp1):
                try:
                    os.remove(p)
                except Exception:
                    pass

        try:
            # Step 1: 提取 f2 首帧
            p = await asyncio.create_subprocess_exec(
                'ffmpeg', '-y', '-ss', '0.05', '-i', f2,
                '-frames:v', '1',
                '-vf', f'scale={W//4}:{H//4}:flags=fast_bilinear',
                '-q:v', '5', frame_b,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await p.communicate()
            if p.returncode != 0 or not os.path.exists(frame_b):
                return False

            # Step 2: 合成仿手机图
            loop = asyncio.get_event_loop()
            built = await loop.run_in_executor(
                None, self._build_phone_still, frame_b, still, W, H
            )
            if not built:
                return False

            # Step 3: 动画 still（zoompan 0.55×→1.0×，共 ANIM_DUR s）
            n_frames = int(ANIM_DUR * 30)
            zoom_vf = (
                f"zoompan=z='if(eq(on,1),0.55,min(zoom+{0.45/n_frames:.5f},1.0))'"
                f":d={n_frames}:x='(iw/2)-(iw/zoom/2)':y='(ih/2)-(ih/zoom/2)'"
                f":s={W}x{H},fps=30"
            )
            p = await asyncio.create_subprocess_exec(
                'ffmpeg', '-y',
                '-loop', '1', '-t', f'{ANIM_DUR + 0.1:.2f}', '-i', still,
                '-vf', f'scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos,'
                       f'pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,{zoom_vf},settb=1/30',
                '-t', f'{ANIM_DUR:.2f}',
                '-c:v', 'h264_videotoolbox', '-b:v', '10M', '-allow_sw', '1',
                '-an', '-pix_fmt', 'yuv420p', anim,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            )
            _, err = await p.communicate()
            if p.returncode != 0 or not os.path.exists(anim):
                logger.warning(f"phone_zoom anim failed: {err.decode()[-200:]}")
                return False

            # 获取 f1 时长
            try:
                pp = await asyncio.create_subprocess_exec(
                    'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                    '-of', 'default=noprint_wrappers=1:nokey=1', f1,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                )
                out, _ = await pp.communicate()
                f1_dur = float(out.strip())
            except Exception:
                f1_dur = 5.0

            # Step 4: xfade f1 → still (fadewhite)
            fade_off1 = max(0.0, f1_dur - FADE_DUR)
            p = await asyncio.create_subprocess_exec(
                'ffmpeg', '-y', '-i', f1, '-i', anim,
                '-filter_complex',
                f'[0:v]settb=1/30[va];[1:v]settb=1/30[vb];'
                f'[va][vb]xfade=transition=fadewhite:duration={FADE_DUR}:offset={fade_off1:.3f}[vout]',
                '-map', '[vout]',
                '-c:v', 'h264_videotoolbox', '-b:v', '10M', '-allow_sw', '1',
                '-an', '-pix_fmt', 'yuv420p', tmp1,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            )
            _, err = await p.communicate()
            if p.returncode != 0 or not os.path.exists(tmp1):
                logger.warning(f"phone_zoom s1 failed: {err.decode()[-200:]}")
                return False

            # Step 5: xfade still → f2 (fadewhite)
            try:
                pp = await asyncio.create_subprocess_exec(
                    'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                    '-of', 'default=noprint_wrappers=1:nokey=1', tmp1,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                )
                out, _ = await pp.communicate()
                tmp1_dur = float(out.strip())
            except Exception:
                tmp1_dur = f1_dur + ANIM_DUR - FADE_DUR

            step2_off = max(0.0, tmp1_dur - FADE_DUR)
            p = await asyncio.create_subprocess_exec(
                'ffmpeg', '-y', '-i', tmp1, '-i', f2,
                '-filter_complex',
                f'[0:v]settb=1/30[va];[1:v]settb=1/30[vb];'
                f'[va][vb]xfade=transition=fadewhite:duration={FADE_DUR}:offset={step2_off:.3f}[vout]',
                '-map', '[vout]',
                '-c:v', 'h264_videotoolbox', '-b:v', '10M', '-allow_sw', '1',
                '-an', '-pix_fmt', 'yuv420p', dst,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            )
            _, err = await p.communicate()
            if p.returncode != 0:
                logger.warning(f"phone_zoom s2 failed: {err.decode()[-200:]}")
                return False

            return os.path.exists(dst) and os.path.getsize(dst) > 0

        except Exception as e:
            logger.error(f"_phone_zoom_merge: {e}")
            return False
        finally:
            await _cleanup()

    async def _phone_zoom_merge_all(
        self, clip_files: List[str], temp_dir: Path
    ) -> Optional[str]:
        """顺序执行 phone_zoom 转场，将 N 个片段合并为 1 个。"""
        import os
        if len(clip_files) == 1:
            return clip_files[0]

        current = clip_files[0]
        for k in range(1, len(clip_files)):
            dst = str(temp_dir / f"pz_merged_{k:02d}.mp4")
            ok  = await self._phone_zoom_merge(current, clip_files[k], dst)
            if not ok:
                logger.warning(f"phone_zoom merge failed at step {k}, falling back to concat")
                # 失败时 fallback：用当前 current + 剩余片段做 concat
                remaining = [current] + clip_files[k:]
                concat_f = temp_dir / "pz_fallback_concat.txt"
                await self._create_concat_file(remaining, concat_f)
                return await self._concat_clips(str(concat_f), temp_dir)
            current = dst

        return current if os.path.exists(current) else None

    async def _xfade_merge(
        self,
        clip_files: List[str],
        clip_durs: List[float],
        tr_type: str,
        tr_dur: float,
        temp_dir: Path,
    ) -> Optional[str]:
        """
        Merge N clips using FFmpeg filter_complex xfade chain.

        Each consecutive pair overlaps by tr_dur seconds:
          [0:v][1:v]xfade=transition=T:duration=D:offset=O1[x1]
          [x1][2:v]xfade=transition=T:duration=D:offset=O2[x2]  ...
          [x{n-2}][{n-1}:v]xfade=...:offset=O_{n-1}[vout]

        Offset_i = sum(clip_durs[0..i-1]) - i * tr_dur
        """
        # Clamp tr_dur to shortest clip to avoid xfade longer than the input
        min_dur = min(clip_durs) if clip_durs else tr_dur
        tr_dur = min(tr_dur, min_dur * 0.8)
        if tr_dur <= 0:
            tr_dur = 0.3

        inputs = []
        for f in clip_files:
            inputs += ['-i', f]

        n = len(clip_files)
        fc_parts = []
        cumulative = 0.0
        for i in range(1, n):
            in_label  = "[0:v]" if i == 1 else f"[x{i-1}]"
            out_label = "[vout]" if i == n - 1 else f"[x{i}]"
            offset = max(0.0, cumulative + clip_durs[i - 1] - tr_dur)
            cumulative = offset  # next offset reference = this clip's effective end
            fc_parts.append(
                f"{in_label}[{i}:v]xfade=transition={tr_type}"
                f":duration={tr_dur:.3f}:offset={offset:.3f}{out_label}"
            )

        out = str(temp_dir / "merged_xfade.mp4")
        proc = await asyncio.create_subprocess_exec(
            'ffmpeg', '-y',
            *inputs,
            '-filter_complex', ';'.join(fc_parts),
            '-map', '[vout]',
            '-c:v', 'h264_videotoolbox', '-b:v', '10M', '-allow_sw', '1',
            '-an',
            out,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning(f"xfade merge failed: {stderr.decode()[-300:]}")
            return None
        if Path(out).exists():
            logger.info(f"xfade merge ({tr_type}) OK: {len(clip_files)} clips → {out}")
            return out
        return None

    async def _final_composition(self, merged_video: str, audio_path: str,
                               output_path: str, style_config: Dict) -> bool:
        """最终合成（将合并好的视频片段与音频合并）"""
        clean_audio_path = None
        try:
            # Pre-convert audio to s16le: CosyVoice2 produces float32 PCM which can contain
            # NaN/Inf samples that crash the AAC encoder. Converting to integer PCM sanitises
            # all invalid values before encoding.
            clean_audio_path = audio_path + "_clean.wav"
            clean_proc = await asyncio.create_subprocess_exec(
                'ffmpeg', '-y', '-i', audio_path,
                '-c:a', 'pcm_s16le',
                '-ar', str(self.output_settings['audio_sample_rate']),
                clean_audio_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await clean_proc.communicate()
            if not Path(clean_audio_path).exists():
                clean_audio_path = audio_path  # fallback to original

            cmd = [
                'ffmpeg', '-y',
                '-i', merged_video,
                '-i', clean_audio_path,
            ]

            cmd.extend([
                '-c:v', 'h264_videotoolbox',
                '-b:v', '10M',
                '-allow_sw', '1',
                '-c:a', 'aac',
                '-b:a', '128k',
                '-ar', str(self.output_settings['audio_sample_rate']),
                '-shortest',  # 以最短的流为准
                output_path
            ])
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                logger.info("Final composition successful")
                return True
            else:
                logger.error(f"Final composition failed: {stderr.decode()}")
                return False

        except Exception as e:
            logger.error(f"Final composition error: {e}")
            return False
        finally:
            # Clean up temp sanitised audio
            if clean_audio_path and clean_audio_path != audio_path:
                try:
                    Path(clean_audio_path).unlink(missing_ok=True)
                except Exception:
                    pass
    
    async def _get_audio_duration(self, audio_path: str) -> float:
        """获取音频/视频文件时长（秒）。优先 format=duration，fallback stream=duration。"""
        for entries in ('format=duration', 'stream=duration'):
            try:
                proc = await asyncio.create_subprocess_exec(
                    'ffprobe', '-v', 'error',
                    '-show_entries', entries,
                    '-of', 'default=noprint_wrappers=1:nokey=1',
                    audio_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                stdout, _ = await proc.communicate()
                for line in stdout.decode().strip().splitlines():
                    line = line.strip()
                    if line and line != 'N/A':
                        try:
                            return float(line)
                        except ValueError:
                            pass
            except Exception as e:
                logger.warning(f"Failed to probe duration ({entries}): {e}")
        return 0.0  # 返回0表示探测失败，调用方自行处理
    
    def get_available_styles(self) -> Dict[str, Dict]:
        """获取可用的视频风格配置"""
        return {
            style: {
                **config,
                'description': self._get_style_description(style)
            }
            for style, config in self.video_configs.items()
        }
    
    def _get_style_description(self, style: str) -> str:
        """获取风格描述"""
        descriptions = {
            'dynamic': '动态效果，包含缩放和转场',
            'smooth': '平滑过渡，柔和的溶解效果',
            'simple': '简洁风格，直接切换无特效'
        }
        return descriptions.get(style, '标准风格')