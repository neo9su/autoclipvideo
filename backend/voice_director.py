"""
配音生成控制器

TTS 优先级：
  1. GPU CosyVoice2（本地高质量，多情感，声音克隆）
  2. MiniMax API（云端备用）
  3. Edge TTS（免费云端兜底）
"""
import asyncio
import logging
import os
import time
from typing import Dict, List, Optional

import aiohttp
import aiosqlite
import httpx

from gpu_execution import reject_local_media, require_remote_gpu

from local_media_guard import local_media_slot

logger = logging.getLogger(__name__)


def _normalize_tts_text(text: str) -> str:
    """Normalize punctuation before cloud TTS/signing.

    Tencent request signing and some fallback clients are sensitive to a few
    unicode punctuation marks. Keep Chinese text intact but replace characters
    that have repeatedly caused encoding/signing issues.
    """
    return (text or "").replace("…", "...").replace("—", "-").strip()

# ── 配置 ───────────────────────────────────────────────────────────────────────
_GPU_SERVICE_URL  = os.environ.get("GPU_SERVICE_URL", "http://10.190.0.203:8877")
_DB_PATH          = os.path.join(os.path.dirname(__file__), "..", "douyin.db")
_MINIMAX_API_KEY  = os.environ.get("MINIMAX_API_KEY", "")
_MINIMAX_GROUP_ID = os.environ.get("MINIMAX_GROUP_ID", "")
_MINIMAX_VOICE    = os.environ.get("MINIMAX_VOICE", "female-shaonv")   # 甜美女声
_EDGE_VOICE       = "zh-CN-XiaoxiaoNeural"

# 腾讯云 TTS（带情感，音质更自然）
_TENCENT_SECRET_ID  = os.environ.get("TENCENT_SECRET_ID", "")
_TENCENT_SECRET_KEY = os.environ.get("TENCENT_SECRET_KEY", "")
# 音色：1001=云小宁(女,支持情感), 1002=云小倩(女), 101001=云希(男)
# 支持情感的音色：1001,1002,1003,1004,1005,1007,1110,100510000 等
_TENCENT_VOICE_TYPE = int(os.environ.get("TENCENT_VOICE_TYPE", "1001"))

# 场景类型 → 腾讯云情感类型
# EmotionCategory: happy/sad/angry/fear/news/story/radio/poetry/calm/lively/customer-service
_TENCENT_EMOTION: Dict[str, str] = {
    "hook":          "lively",
    "problem":       "sad",
    "solution":      "happy",
    "demonstration": "news",
    "social_proof":  "story",
    "transformation":"happy",
    "promotion":     "lively",
    "urgency":       "lively",
    "cta":           "lively",
}

# 场景类型 → 情感（对应 GPU TTS emotion 字段）
# 覆盖所有新 scene_type（director_script.py 中定义的9种）
_SCENE_EMOTION: Dict[str, str] = {
    # 新 vibe 系统场景类型
    "hook":          "excited",
    "problem":       "emotional",
    "solution":      "warm",
    "demonstration": "confident",
    "social_proof":  "storytelling",
    "transformation":"excited",
    "promotion":     "urgent",
    "urgency":       "urgent",
    "cta":           "persuasive",
    # 旧场景类型（向后兼容）
    "product_intro":  "warm",
    "try_on":         "warm",
    "comparison":     "clear",
    "trust_building": "natural",
    "closing":        "persuasive",
    "opening":        "excited",
    "demonstration_legacy": "confident",
    "luxury_showcase":"luxury",
}


class VoiceDirector:
    def __init__(self):
        self._output_dir = os.path.join(os.path.dirname(__file__), "..", "voice_output")
        os.makedirs(self._output_dir, exist_ok=True)

    # ── 声音克隆参考 ───────────────────────────────────────────────────────────

    async def _get_or_create_room_voice_ref(self, group_id: int) -> Optional[str]:
        """
        每个直播间维护一个声音克隆参考 clip job ID（rooms.voice_ref_clip_job_id）。
        首次调用时从该直播间最新录像截取 30s，提交 GPU clip job 后等待完成，
        将 job_id 写入 DB 以便下次复用。
        """
        async with aiosqlite.connect(_DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT cg.room_id, r.voice_ref_clip_job_id
                   FROM clip_groups cg
                   JOIN rooms r ON r.id = cg.room_id
                   WHERE cg.id = ?""",
                (group_id,),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            logger.warning(f"Group {group_id} not found or no room")
            return None

        room_id: int = row["room_id"]
        existing: Optional[str] = row["voice_ref_clip_job_id"]

        if existing:
            # 验证 voice ref 仍然存在于 GPU 服务器
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{_GPU_SERVICE_URL}/voice-refs/{existing}",
                                           timeout=aiohttp.ClientTimeout(total=5)) as r:
                        if r.status == 200:
                            body = await r.json()
                            if body.get("status") == "done":
                                logger.debug(f"Reusing voice ref {existing} for room {room_id}")
                                return existing
            except Exception:
                pass
            logger.info(f"Voice ref {existing} stale or missing, recreating for room {room_id}")

        # 找合适录像（需 >2MB，优先最新）
        _recordings_dir = os.path.join(os.path.dirname(__file__), "..", "recordings")
        async with aiosqlite.connect(_DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT filename FROM recordings
                   WHERE room_id = ? AND filename IS NOT NULL
                   ORDER BY id DESC LIMIT 50""",
                (room_id,),
            ) as cur:
                candidates = await cur.fetchall()

        rec_filename = None
        for cand in candidates:
            local_p = os.path.join(_recordings_dir, cand["filename"])
            if os.path.exists(local_p) and os.path.getsize(local_p) > 2_000_000:
                rec_filename = cand["filename"]
                break

        if not rec_filename:
            logger.warning(f"No suitable recording for room {room_id} voice ref")
            return None

        local_path = os.path.join(_recordings_dir, rec_filename)

        # 提交 /voice-refs 轻量提取（只提取音频，不走 NVENC 视频流水线）
        payload = {
            "mp4_filename": rec_filename,
            "room_id": room_id,
            "start": 5.0,
            "end": 28.0,   # CosyVoice2 inference_instruct2 limit: <30s
        }

        async def _submit_voice_ref() -> Optional[str]:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{_GPU_SERVICE_URL}/voice-refs", json=payload,
                                        timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    _sc = resp.status
                    _body = await resp.json() if _sc in (200, 201) else None
                    _text = await resp.text() if _body is None else ""
            if _sc == 201:
                return _body["ref_id"]
            if _sc == 404 and os.path.exists(local_path):
                # 文件不在 GPU 服务器，先上传
                logger.info(f"Uploading {rec_filename} to GPU for voice ref...")
                try:
                    from sync import sync_file
                    await sync_file(local_path, room_id)
                    await asyncio.sleep(2)
                except Exception as ue:
                    logger.warning(f"Voice ref upload failed: {ue}")
                    return None
                # 重试
                async with aiohttp.ClientSession() as session:
                    async with session.post(f"{_GPU_SERVICE_URL}/voice-refs", json=payload,
                                            timeout=aiohttp.ClientTimeout(total=15)) as resp2:
                        _sc2 = resp2.status
                        _body2 = await resp2.json() if _sc2 == 201 else None
                if _sc2 == 201:
                    return _body2["ref_id"]
                logger.warning(f"Voice ref retry failed: {_sc2}")
                return None
            logger.warning(f"Voice ref submit failed: {_sc} {_text[:100]}")
            return None

        try:
            ref_id = await _submit_voice_ref()
        except Exception as e:
            logger.warning(f"Voice ref exception: {e}")
            return None
        if not ref_id:
            return None

        # 轮询完成（最多 60 秒 — 只是 ffmpeg 音频提取，很快）
        deadline = time.time() + 60
        while time.time() < deadline:
            await asyncio.sleep(2)
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{_GPU_SERVICE_URL}/voice-refs/{ref_id}",
                                           timeout=aiohttp.ClientTimeout(total=10)) as r:
                        if r.status != 200:
                            break
                        data = await r.json()
                status = data.get("status")
                if status == "done":
                    break
                elif status == "error":
                    logger.warning(f"Voice ref error: {data.get('error')}")
                    return None
            except Exception:
                pass
        else:
            logger.warning(f"Voice ref timed out for room {room_id}")
            return None

        # 写入 DB
        async with aiosqlite.connect(_DB_PATH) as db:
            await db.execute(
                "UPDATE rooms SET voice_ref_clip_job_id = ? WHERE id = ?",
                (ref_id, room_id),
            )
            await db.commit()
        logger.info(f"Voice ref {ref_id} created for room {room_id} ({rec_filename})")
        return ref_id

    # ── 公共入口 ───────────────────────────────────────────────────────────────

    async def generate_voiceover(
        self,
        script: Dict,
        group_id: int,
        reference_audio_path: Optional[str] = None,
    ) -> Dict:
        """
        生成导演脚本完整配音。

        逐场景合成，最后 ffmpeg 拼合。若 scenes 为空则退化为全文合成。
        每个直播间使用同一个声音克隆参考（rooms.voice_ref_clip_job_id）。
        """
        # 获取该分组对应的直播间 room_id（优先走 room_id 模式，自动使用最新 v3 声音克隆）
        room_id_for_tts: Optional[int] = None
        async with aiosqlite.connect(_DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT room_id FROM clip_groups WHERE id = ?", (group_id,)
            ) as cur:
                _grp = await cur.fetchone()
            if _grp:
                room_id_for_tts = _grp["room_id"]

        if room_id_for_tts:
            logger.info(f"TTS will use room_id={room_id_for_tts} voice clone (v3) for group {group_id}")
        else:
            logger.info(f"No room_id for group {group_id}, using Edge TTS fallback")

        scenes: List[Dict] = script.get("scenes", [])
        is_creative = script.get("vibe") == "creative"
        is_qianchuan = script.get("mode") == "qianchuan"
        if not scenes:
            return await self._synthesize_full_text(script, group_id, room_id_for_tts)

        audio_segments: List[Dict] = []
        total_duration = 0.0

        for scene in scenes:
            text = scene.get("voiceover_text", "").strip()
            if not text:
                continue
            emotion = _SCENE_EMOTION.get(scene.get("scene_type", ""), "natural")
            out_path = os.path.join(
                self._output_dir,
                f"group{group_id}_scene{scene.get('scene_id', 0)}_{int(time.time())}.wav",
            )
            scene_type = scene.get("scene_type", "")
            duration = await self._tts(text, out_path, emotion, room_id_for_tts, scene_type,
                                       is_creative=is_creative)
            if duration > 0:
                audio_segments.append({
                    "scene_id":        scene.get("scene_id"),
                    "audio_path":      out_path,
                    "duration":        duration,
                    "timestamp_start": scene.get("timestamp_start", 0),
                    "timestamp_end":   scene.get("timestamp_end", 0),
                })
                total_duration += duration
            else:
                logger.warning(f"TTS failed for scene {scene.get('scene_id')}, skipping")

        if not audio_segments:
            return {"success": False, "error": "所有场景配音生成失败"}

        merged = await self._merge_audio_segments(audio_segments, group_id)
        if not merged:
            # Older GPU workers may not yet expose audio-concat-jobs. Keep the
            # pipeline usable by synthesizing one normalized remote-GPU track.
            fallback_text = "。".join(
                scene.get("voiceover_text", "").strip()
                for scene in scenes
                if scene.get("voiceover_text", "").strip()
            )
            fallback_path = os.path.join(
                self._output_dir, f"group{group_id}_fallback_{int(time.time())}.wav"
            )
            fallback_duration = await self._tts(
                fallback_text, fallback_path, "natural", room_id_for_tts,
                scene_type="qianchuan_fallback", is_creative=is_creative,
            ) if fallback_text else 0.0
            if fallback_duration > 0:
                logger.warning(
                    "Audio concat unavailable; using one-track remote TTS fallback for group %s",
                    group_id,
                )
                merged = fallback_path
                total_duration = fallback_duration
            else:
                return {"success": False, "error": "音频合并失败（远程拼接不可用，单轨兜底也失败）"}
        if not merged:
            return {"success": False, "error": "音频合并失败"}

        # ── 时长保底：自编/导演模式合成音频 < 30s 时自动降速拉长 ──────────────
        _MIN_AUDIO_DUR = 30.0
        actual_merged_dur = await self._probe_duration(merged)
        if (not is_qianchuan) and actual_merged_dur > 0 and actual_merged_dur < _MIN_AUDIO_DUR:
            stretch_ratio = _MIN_AUDIO_DUR / actual_merged_dur  # e.g. 16s→30s = 1.875x 拉慢
            stretch_ratio = min(stretch_ratio, 2.0)  # atempo 下限 0.5，即最多拉慢2倍
            atempo_val = 1.0 / stretch_ratio          # atempo<1 = 降速
            stretched_path = merged + "_stretched.wav"
            logger.info(f"Creative audio too short ({actual_merged_dur:.1f}s < {_MIN_AUDIO_DUR}s), "
                        f"stretching {stretch_ratio:.2f}x (atempo={atempo_val:.3f})")
            async with local_media_slot("voice director audio stretch"):
                proc = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-y", "-i", merged,
                    "-filter:a", f"atempo={atempo_val:.3f}",
                    stretched_path,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.communicate()
            if os.path.exists(stretched_path) and os.path.getsize(stretched_path) > 0:
                os.replace(stretched_path, merged)
                total_duration = await self._probe_duration(merged)
                logger.info(f"Audio stretched to {total_duration:.1f}s")
            else:
                logger.warning("Audio stretch failed, keeping original (may be too short)")
        # ─────────────────────────────────────────────────────────────────────

        return {
            "success":             True,
            "audio_segments":      audio_segments,
            "merged_audio_path":   merged,
            "total_duration":      total_duration,
            "reference_audio_used": room_id_for_tts,
        }

    # ── TTS 调度链 ─────────────────────────────────────────────────────────────

    async def _tts(
        self,
        text: str,
        output_path: str,
        emotion: str = "natural",
        room_id: Optional[int] = None,
        scene_type: str = "",
        is_creative: bool = False,
    ) -> float:
        """合成单段文字 → WAV/MP3。返回时长秒数，失败返回 0。

        优先级：GPU CosyVoice2 声音克隆（room_id，最高优先） → 腾讯云 TTS → MiniMax → Edge TTS
        """

        # Remote GPU is the only permitted TTS provider, with or without a voice ref.
        dur = await self._tts_gpu(text, output_path, emotion, room_id=room_id,
                                  is_creative=is_creative)
        if dur > 0:
            return dur

        # Remote GPU is the only permitted TTS provider.
        logger.error("GPU TTS unavailable; waiting/retry is required, no fallback is allowed")
        return 0.0

    # ── GPU TTS (CosyVoice2) ───────────────────────────────────────────────────

    async def _resolve_best_voice_ref(self, room_id: int) -> Optional[str]:
        """查询 GPU 服务上该直播间的 done voice refs，优先返回 v3 的 ref_id。"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{_GPU_SERVICE_URL}/voice-refs",
                                       timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status != 200:
                        return None
                    body = await resp.json()
            refs = body if isinstance(body, list) else body.get("refs", [])
            done_refs = [r for r in refs if r.get("room_id") == room_id and r.get("status") == "done"]
            if not done_refs:
                return None
            # 优先选最高版本号：v4 > v3 > v2 > v1 > 其他
            for ver in ("v4", "v3", "v2", "v1"):
                match = [r for r in done_refs if ver in (r.get("label") or "").lower()]
                if match:
                    return match[0]["ref_id"]
            # 兜底：返回最后一个
            return done_refs[-1]["ref_id"]
        except Exception as e:
            logger.warning(f"_resolve_best_voice_ref failed: {e}")
            return None

    async def _tts_gpu(
        self,
        text: str,
        output_path: str,
        emotion: str,
        voice_ref_job_id: str = "",
        room_id: Optional[int] = None,
        is_creative: bool = False,
    ) -> float:
        """提交 GPU TTS 任务，轮询完成后下载 WAV。

        优先使用 room_id（自动选用该直播间最新声音克隆），
        其次 voice_ref_job_id（旧版 clip-based ref）。
        """
        require_remote_gpu("remote TTS")
        # creative vibe 用快速节奏；普通导演模式 KUKU公主额外+10%
        if is_creative:
            _base_speed = 1.35 if room_id == 2 else 1.25
        else:
            _base_speed = 1.21 if room_id == 2 else 1.1
        payload: Dict = {"text": text, "emotion": emotion, "speed": _base_speed}
        if room_id:
            # 主动查询该 room 的 done refs，优先选 v3（label 含 v3），否则按列表最后一个
            resolved_ref_id = await self._resolve_best_voice_ref(room_id)
            if resolved_ref_id:
                payload["ref_voice_id"] = resolved_ref_id
                logger.info(f"TTS: using resolved voice ref {resolved_ref_id} for room {room_id}")
            else:
                payload["room_id"] = room_id      # fallback: GPU 自动选
        elif voice_ref_job_id:
            payload["ref_voice_id"] = voice_ref_job_id
        try:
            # Retry GPU TTS submit (GPU may be temporarily offline)
            _tts_sc = None
            _tts_body = None
            job_id = None
            for _tts_retry in range(3):
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(f"{_GPU_SERVICE_URL}/tts-jobs", json=payload,
                                                timeout=aiohttp.ClientTimeout(total=15)) as resp:
                            _tts_sc = resp.status
                            _tts_body = await resp.json() if _tts_sc == 201 else None
                    if _tts_sc == 201:
                        job_id = _tts_body["job_id"]
                        break
                    elif _tts_sc >= 500:
                        logger.warning(f"GPU TTS returned {_tts_sc}: {_tts_body!r}, retry {_tts_retry+1}/3")
                        await asyncio.sleep(3 * (_tts_retry + 1))
                    else:
                        logger.warning(f"GPU TTS submit failed: {_tts_sc}")
                        return 0.0
                except (aiohttp.ClientConnectorError, aiohttp.ClientOSError, aiohttp.ServerDisconnectedError) as ce:
                    logger.warning(f"GPU TTS connection error, retry {_tts_retry+1}/3: {ce}")
                    await asyncio.sleep(3 * (_tts_retry + 1))
                except Exception as te:
                    logger.warning(f"GPU TTS unexpected error, retry {_tts_retry+1}/3: {te}")
                    await asyncio.sleep(3 * (_tts_retry + 1))
            if job_id is None:
                logger.warning("GPU TTS failed after 3 retries, falling back to Tencent")
                return 0.0

            # Poll with a bounded per-scene deadline. The outer director pipeline has its
            # own voiceover-stage timeout; keeping this shorter makes failures actionable
            # instead of surfacing as a vague 30 minute pipeline timeout.
            gpu_tts_timeout = int(os.environ.get("GPU_TTS_JOB_TIMEOUT_SECONDS", "300"))
            deadline = time.time() + gpu_tts_timeout
            while time.time() < deadline:
                await asyncio.sleep(2)
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{_GPU_SERVICE_URL}/tts-jobs/{job_id}",
                                           timeout=aiohttp.ClientTimeout(total=10)) as r:
                        if r.status != 200:
                            logger.warning(f"GPU TTS poll {job_id} returned {r.status}, aborting")
                            return 0.0
                        r_body = await r.json()
                status = r_body.get("status")
                if status == "done":
                    break
                elif status == "error":
                    logger.warning(f"GPU TTS error for job {job_id}: {r_body.get('error')}")
                    return 0.0
            else:
                logger.warning(f"GPU TTS timed out after {gpu_tts_timeout}s for job {job_id}")
                return 0.0

            # 下载音频
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{_GPU_SERVICE_URL}/tts-jobs/{job_id}/audio",
                                       timeout=aiohttp.ClientTimeout(total=60)) as audio_resp:
                    if audio_resp.status != 200:
                        return 0.0
                    audio_data = await audio_resp.read()
            with open(output_path, "wb") as f:
                f.write(audio_data)
            if os.path.getsize(output_path) == 0:
                return 0.0
            actual_dur = await self._probe_duration(output_path)
            if actual_dur <= 0:
                logger.warning("GPU TTS returned audio but duration could not be read")
            # Speed correction must be performed by the remote GPU service.
            return actual_dur

        except Exception as e:
            logger.warning(f"GPU TTS exception for scene_type={scene_type}: {type(e).__name__}: {e}")
            return 0.0

    # ── MiniMax 云端 TTS ───────────────────────────────────────────────────────

    async def _tts_minimax(self, text: str, output_path: str) -> float:
        url = f"https://api.minimax.chat/v1/t2a_v2?GroupId={_MINIMAX_GROUP_ID}"
        payload = {
            "model": "speech-02-hd",
            "text": text,
            "stream": False,
            "voice_setting": {
                "voice_id": _MINIMAX_VOICE,
                "speed": 1.0, "vol": 1.0, "pitch": 0,
            },
            "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3"},
        }
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {_MINIMAX_API_KEY}",
                        "Content-Type": "application/json",
                    },
                )
            if resp.status_code != 200:
                logger.error(f"MiniMax TTS {resp.status_code}: {resp.text[:200]}")
                return 0.0
            hex_audio = resp.json().get("data", {}).get("audio", "")
            if not hex_audio:
                return 0.0
            with open(output_path, "wb") as f:
                f.write(bytes.fromhex(hex_audio))
            return await self._probe_duration(output_path)
        except Exception as e:
            logger.error(f"MiniMax TTS exception: {e}")
            return 0.0

    # ── 腾讯云 TTS ────────────────────────────────────────────────────────────

    async def _tts_tencent(
        self,
        text: str,
        output_path: str,
        emotion: str = "",
        secret_id: str = "",
        secret_key: str = "",
    ) -> float:
        """腾讯云 TTS（带情感，自然中文语音）。返回时长秒数，失败返回 0。"""
        _sid = secret_id or _TENCENT_SECRET_ID
        _skey = secret_key or _TENCENT_SECRET_KEY
        if not _sid or not _skey:
            return 0.0
        try:
            import base64
            import hashlib
            import hmac
            import json as _json
            from datetime import datetime, timezone

            service = "tts"
            host = "tts.tencentcloudapi.com"
            region = "ap-guangzhou"
            action = "TextToVoice"
            version = "2019-08-23"
            timestamp = int(time.time())
            date = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")

            payload_dict = {
                "Text": text,
                "SessionId": f"douyin_{int(time.time() * 1000)}",
                "VoiceType": _TENCENT_VOICE_TYPE,
                "Codec": "mp3",
                "SampleRate": 16000,
                "Speed": 0,
                "Volume": 0,
            }
            if emotion:
                payload_dict["EmotionCategory"] = emotion
                payload_dict["EmotionIntensity"] = 100

            payload_str = _json.dumps(payload_dict, separators=(',', ':'))

            # TC3-HMAC-SHA256 签名
            def _sign(key: bytes, msg: str) -> bytes:
                return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

            hashed_payload = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()
            canonical_request = (
                f"POST\n/\n\ncontent-type:application/json\nhost:{host}\n"
                f"x-tc-action:{action.lower()}\n\n"
                f"content-type;host;x-tc-action\n{hashed_payload}"
            )
            credential_scope = f"{date}/{service}/tc3_request"
            string_to_sign = (
                f"TC3-HMAC-SHA256\n{timestamp}\n{credential_scope}\n"
                + hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
            )
            secret_date    = _sign(("TC3" + _skey).encode("utf-8"), date)
            secret_service = _sign(secret_date, service)
            secret_signing = _sign(secret_service, "tc3_request")
            signature = hmac.new(
                secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256
            ).hexdigest()

            authorization = (
                f"TC3-HMAC-SHA256 Credential={_sid}/{credential_scope}, "
                f"SignedHeaders=content-type;host;x-tc-action, Signature={signature}"
            )
            headers = {
                "Authorization":  authorization,
                "Content-Type":   "application/json",
                "Host":           host,
                "X-TC-Action":    action,
                "X-TC-Timestamp": str(timestamp),
                "X-TC-Version":   version,
                "X-TC-Region":    region,
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"https://{host}", headers=headers, content=payload_str
                )
            if resp.status_code != 200:
                logger.error(f"Tencent TTS HTTP {resp.status_code}: {resp.text[:200]}")
                return 0.0
            result = resp.json().get("Response", {})
            if result.get("Error"):
                logger.error(f"Tencent TTS API error: {result['Error']}")
                return 0.0
            audio_b64 = result.get("Audio", "")
            if not audio_b64:
                return 0.0
            audio_bytes = base64.b64decode(audio_b64)
            with open(output_path, "wb") as f:
                f.write(audio_bytes)
            dur = await self._probe_duration(output_path)
            logger.info(f"Tencent TTS: {len(text)} chars → {dur:.1f}s (emotion={emotion or 'none'})")
            return dur
        except Exception as e:
            logger.error(f"Tencent TTS exception: {e}")
            return 0.0

    # ── Edge TTS (免费兜底) ────────────────────────────────────────────────────

    async def _tts_edge(self, text: str, output_path: str) -> float:
        try:
            import edge_tts
            communicate = edge_tts.Communicate(text, _EDGE_VOICE)
            await communicate.save(output_path)
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                return await self._probe_duration(output_path)
        except ImportError:
            logger.error("edge-tts not installed: pip install edge-tts")
        except Exception as e:
            logger.error(f"Edge TTS exception: {e}")
        return 0.0

    # ── 音频工具 ───────────────────────────────────────────────────────────────

    async def _probe_duration(self, path: str) -> float:
        """ffprobe 获取音频时长（秒）。"""
        try:
            import wave
            with wave.open(path, "rb") as wav_file:
                frame_rate = wav_file.getframerate()
                frame_count = wav_file.getnframes()
            return frame_count / frame_rate if frame_rate else 0.0
        except Exception as error:
            logger.warning("Unable to read WAV duration for %s: %s", os.path.basename(path), error)
            return 0.0

    async def _merge_audio_segments(self, segments: List[Dict], group_id: int) -> Optional[str]:
        """顺序拼合所有音频片段。"""
        if len(segments) == 1:
            return segments[0]["audio_path"]

        merged_path = os.path.join(
            self._output_dir, f"group{group_id}_merged_{int(time.time())}.wav"
        )
        list_file = merged_path + ".txt"
        try:
            async with aiohttp.ClientSession() as session:
                form = aiohttp.FormData()
                for segment in segments:
                    segment_path = segment["audio_path"]
                    with open(segment_path, "rb") as audio_file:
                        form.add_field("files", audio_file.read(), filename=os.path.basename(segment_path), content_type="audio/wav")
                async with session.post(f"{_GPU_SERVICE_URL}/audio-concat-jobs", data=form, timeout=aiohttp.ClientTimeout(total=60)) as response:
                    if response.status != 201:
                        logger.error("Remote audio concat submit failed: %s", await response.text())
                        return None
                    job_id = (await response.json())["job_id"]
                deadline = time.time() + 180
                while time.time() < deadline:
                    await asyncio.sleep(2)
                    async with session.get(f"{_GPU_SERVICE_URL}/audio-concat-jobs/{job_id}", timeout=aiohttp.ClientTimeout(total=10)) as status_response:
                        status = await status_response.json()
                    if status.get("status") == "error":
                        logger.error("Remote audio concat failed: %s", status.get("error"))
                        return None
                    if status.get("status") == "done":
                        break
                else:
                    logger.error("Remote audio concat timed out for job %s", job_id)
                    return None
                async with session.get(f"{_GPU_SERVICE_URL}/audio-concat-jobs/{job_id}/audio", timeout=aiohttp.ClientTimeout(total=60)) as audio_response:
                    if audio_response.status != 200:
                        logger.error("Remote audio concat download failed: %s", audio_response.status)
                        return None
                    audio_data = await audio_response.read()
            with open(merged_path, "wb") as merged_file:
                merged_file.write(audio_data)
            try:
                os.remove(list_file)
            except OSError:
                pass
            for segment in segments:
                try:
                    os.remove(segment["audio_path"])
                except OSError:
                    logger.debug("Unable to remove temporary TTS segment", exc_info=True)
            return merged_path
        except Exception as error:
            try:
                os.remove(list_file)
            except OSError:
                pass
            logger.error("Remote audio concat request failed: %s: %s", type(error).__name__, error)
            return None

    async def _synthesize_full_text(
        self,
        script: Dict,
        group_id: int,
        room_id: Optional[int] = None,
    ) -> Dict:
        """兜底：合并所有场景文本，一次性合成。"""
        texts = [
            scene.get("voiceover_text", "")
            for scene in script.get("scenes", [])
            if scene.get("voiceover_text")
        ] or [script.get("text", "")]
        full_text = "。".join(t.strip() for t in texts if t.strip())
        if not full_text:
            return {"success": False, "error": "脚本无配音文本"}
        out_path = os.path.join(
            self._output_dir, f"group{group_id}_full_{int(time.time())}.wav"
        )
        duration = await self._tts(full_text, out_path, "natural", room_id)
        if duration <= 0:
            return {"success": False, "error": "全文配音合成失败"}
        return {
            "success":             True,
            "audio_segments":      [],
            "merged_audio_path":   out_path,
            "total_duration":      duration,
            "reference_audio_used": room_id,
        }
