"""
Audio + visual quality scoring for segment selection — Phase B, C & D.

Phase B (audio):    ffmpeg volumedetect — loudness/dynamic range per segment.
                    No new dependencies.
Phase C (visual):   OpenCV Laplacian sharpness + face detection per segment.
                    Requires: opencv-python  (pip install opencv-python-headless)
                    Gracefully degrades to no-op when OpenCV is not installed.
Phase D (semantic): Claude Haiku vision — wig visibility, demo quality, etc.
                    Requires: imagehash Pillow  (pip install imagehash Pillow)
                    Requires: AWS_BEARER_TOKEN_BEDROCK env var
                    Gracefully degrades to no-op when dependencies/token missing.
                    Cost: ~$0.008/recording (15 segs × 2 frames × Haiku image price)

Integration:
    from segment_scorer import enrich_audio_scores, enrich_visual_scores, enrich_semantic_scores
    await enrich_audio_scores(mp4_path, segs)      # after score_and_tag + silence filter
    await enrich_visual_scores(mp4_path, segs)     # after audio scoring
    await enrich_semantic_scores(mp4_path, segs)   # after visual scoring
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

_GPU_SERVICE_URL = os.environ.get("GPU_SERVICE_URL", "http://10.190.0.203:8877")

# GPU can handle multiple concurrent frame-extract requests (video already there).
_SEM_GPU_FRAME = asyncio.Semaphore(4)

# Max concurrent volumedetect processes (audio-only decode, CPU-light).
_SEM_AUDIO = asyncio.Semaphore(1)

# Local ffmpeg fallback — kept at 1 to avoid CPU saturation on M2 8GB.
_SEM_FRAME = asyncio.Semaphore(1)


async def _volumedetect(mp4: str, start: float, end: float) -> dict:
    """
    Run ffmpeg volumedetect on [start, end] of mp4.
    Returns {"mean_db": float, "max_db": float} or {} on failure.

    ffmpeg volumedetect output example (stderr):
      [Parsed_volumedetect_0 @ ...] mean_volume: -20.3 dB
      [Parsed_volumedetect_0 @ ...] max_volume: -6.2 dB
    """
    # -nostdin avoids ffmpeg waiting for stdin on some platforms
    cmd = [
        "ffmpeg", "-nostdin", "-y",
        "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
        "-i", mp4,
        "-af", "volumedetect",
        "-f", "null", "-",
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
    except Exception as e:
        logger.debug(f"volumedetect spawn failed: {e}")
        return {}

    text = stderr.decode("utf-8", errors="replace")
    mean_m = re.search(r"mean_volume:\s*([-\d.]+)\s*dB", text)
    max_m  = re.search(r"max_volume:\s*([-\d.]+)\s*dB", text)

    if not mean_m:
        return {}

    return {
        "mean_db": float(mean_m.group(1)),
        "max_db":  float(max_m.group(1)) if max_m else float(mean_m.group(1)),
    }


def _audio_bonus(mean_db: float, max_db: float) -> float:
    """
    Translate raw audio stats into a score addend.

    mean_db : RMS average level (dBFS). Higher = louder / more energetic.
              Live-stream anchor speech typically ranges -28 to -18 dBFS.
    max_db  : Peak level. (max_db - mean_db) = dynamic range.

    Rationale:
      - Loud/excited delivery (+energy): better hook material, keeps viewers.
      - High dynamic range (punchy emphasis, "秒变！"): emotional peak moments.
      - Very quiet / near-silent: likely transition noise or dead air; penalise.

    Return range: approximately [-6, +7.5].
    """
    bonus = 0.0

    # ── Loudness (mean RMS) ───────────────────────────────────────────────────
    if mean_db > -18:       bonus += 5.0   # excited/shouting — high energy hook
    elif mean_db > -22:     bonus += 3.5   # energetic delivery
    elif mean_db > -28:     bonus += 1.5   # normal speech
    elif mean_db > -35:     bonus += 0.0   # quiet (still valid)
    else:                   bonus -= 4.0   # near-silent; may have slipped past silence filter

    # ── Dynamic range (peak − mean) ──────────────────────────────────────────
    dynamic = max_db - mean_db
    if dynamic > 20:        bonus += 2.5   # very dynamic — shouts, emphasis
    elif dynamic > 14:      bonus += 1.5   # moderate dynamic
    elif dynamic > 8:       bonus += 0.5   # mildly dynamic

    return bonus


async def enrich_audio_scores(mp4: str, segs: list) -> None:
    """
    Enrich seg.score with an audio energy bonus for every valid segment.

    Runs all volumedetect jobs concurrently (bounded semaphore).
    Modifies segs in-place — call after score_and_tag() and the silence filter,
    but before select_clips().

    Hard filter: if mean_db < -45 dBFS the segment is effectively silent even
    if it passed the 60%-silence-ratio check; marks seg.valid = False.
    """
    valid = [s for s in segs if s.valid]
    if not valid:
        return

    async def _one(seg) -> None:
        async with _SEM_AUDIO:
            stats = await _volumedetect(mp4, seg.start, seg.end)

        if not stats:
            return  # failed — leave score unchanged

        mean_db = stats["mean_db"]
        max_db  = stats["max_db"]

        # Hard filter: near-silent segments that passed the 60%-ratio gate
        if mean_db < -45:
            seg.valid = False
            logger.debug(
                f"Audio hard-filter (near-silent) [{seg.start:.1f}-{seg.end:.1f}]"
                f" mean={mean_db:.1f}dB"
            )
            return

        bonus = _audio_bonus(mean_db, max_db)
        seg.score = round(seg.score + bonus, 2)
        logger.debug(
            f"Audio [{seg.start:.1f}-{seg.end:.1f}] "
            f"mean={mean_db:.1f}dB max={max_db:.1f}dB "
            f"bonus={bonus:+.1f} → score={seg.score:.1f}"
        )

    await asyncio.gather(*[_one(s) for s in valid])
    enriched = sum(1 for s in valid if s.valid)
    filtered  = len(valid) - enriched
    logger.info(
        f"Audio scoring complete: {enriched} enriched, {filtered} hard-filtered"
        f" ({len(valid)} total valid)"
    )


# ── Phase C: Visual quality scoring ──────────────────────────────────────────

# Max concurrent frame-extract + OpenCV jobs.
# Each needs a brief ffmpeg decode; keep at 1 to avoid CPU saturation on M2 8GB.
_SEM_VISUAL = asyncio.Semaphore(1)

# Sharpness thresholds (Laplacian variance on grayscale frame, 1080×1920 crop)
_SHARP_HARD_MIN  = 10.0    # below this → severe blur → seg.valid = False (lowered: motion blur in demos is acceptable)
_SHARP_SOFT_LOW  = 80.0    # below this → visible blur → mild penalty
_SHARP_GOOD      = 200.0   # above this → crisp         → bonus
_SHARP_EXCELLENT = 500.0   # above this → very sharp     → extra bonus

# Haar cascade path (bundled with opencv-python)
_HAAR_FRONTAL = None   # loaded lazily once per process


def _get_face_cascade():
    global _HAAR_FRONTAL
    if _HAAR_FRONTAL is None:
        import cv2
        path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        _HAAR_FRONTAL = cv2.CascadeClassifier(path)
    return _HAAR_FRONTAL


async def _extract_frame_gpu(job_id: str, ts: float) -> Optional[str]:
    """Try to extract a frame from the GPU server (video already uploaded there).
    Returns a local temp JPEG path, or None if GPU is unavailable/job not found."""
    try:
        import aiohttp as _aio
        async with _SEM_GPU_FRAME:
            async with _aio.ClientSession() as session:
                async with session.post(
                    f"{_GPU_SERVICE_URL}/jobs/{job_id}/extract-frames",
                    json={"timestamps": [ts]},
                    timeout=_aio.ClientTimeout(total=20),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        frame_b64 = data.get("frames", [None])[0]
                        if frame_b64:
                            fd, path = tempfile.mkstemp(suffix=".jpg")
                            os.close(fd)
                            with open(path, "wb") as f:
                                f.write(base64.b64decode(frame_b64))
                            return path
    except Exception as e:
        logger.debug(f"GPU frame extract failed for {job_id} at {ts:.1f}s: {e}")
    return None


async def _extract_frame(mp4: str, ts: float) -> Optional[str]:
    """
    Extract a single frame at timestamp ts from mp4.
    Tries GPU server first (video already there); falls back to local ffmpeg.
    Returns path to a temp JPEG, or None on failure.
    Caller is responsible for deleting the file.
    """
    # GPU-first: derive job_id from mp4 filename (matches GPU storage key)
    job_id = os.path.splitext(os.path.basename(mp4))[0]
    path = await _extract_frame_gpu(job_id, ts)
    if path:
        return path

    # Local ffmpeg fallback
    fd, path = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)
    # Two-pass seek: coarse -ss before -i (fast), fine -ss after for accuracy
    pre  = max(0.0, ts - 2.0)
    fine = ts - pre
    cmd = [
        "ffmpeg", "-nostdin", "-y",
        "-ss", f"{pre:.3f}", "-i", mp4,
        "-ss", f"{fine:.3f}", "-frames:v", "1",
        "-vf", "scale=540:960:force_original_aspect_ratio=decrease",
        "-q:v", "4", path,
    ]
    try:
        async with _SEM_FRAME:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate()
        if proc.returncode == 0 and os.path.exists(path) and os.path.getsize(path) > 0:
            return path
    except Exception as e:
        logger.debug(f"Frame extract failed at {ts:.1f}s: {e}")
    try:
        os.remove(path)
    except Exception:
        pass
    return None


def _analyse_frame(frame_path: str) -> dict:
    """
    Run synchronous OpenCV analysis on a JPEG frame.
    Returns:
      sharpness  : Laplacian variance (float, 0→∞)
      face_ratio : largest face area / total frame area (0.0–1.0)
      brightness : mean pixel intensity (0–255)
    """
    import cv2
    import numpy as np

    img = cv2.imread(frame_path)
    if img is None:
        return {}

    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Sharpness: Laplacian variance — blurry frames give low values
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    # Face detection — quick run at reduced scale factor
    cascade = _get_face_cascade()
    faces = cascade.detectMultiScale(
        gray,
        scaleFactor=1.15,
        minNeighbors=4,
        minSize=(30, 30),
    )
    face_ratio = 0.0
    if len(faces) > 0:
        # Largest face
        areas = [fw * fh for (_, _, fw, fh) in faces]
        face_ratio = max(areas) / (w * h)

    brightness = float(np.mean(gray))

    return {
        "sharpness":  sharpness,
        "face_ratio": face_ratio,
        "brightness": brightness,
    }


def _visual_bonus(sharpness: float, face_ratio: float, brightness: float) -> float:
    """
    Compute score addend from visual quality metrics.

    sharpness  : Laplacian variance (higher = sharper).
    face_ratio : largest detected face as fraction of frame area.
    brightness : mean pixel value 0–255.

    Return range: approximately [-5, +9].
    """
    bonus = 0.0

    # ── Sharpness ─────────────────────────────────────────────────────────────
    # Hard filter handled by caller; here only soft adjustments.
    if sharpness >= _SHARP_EXCELLENT:   bonus += 4.0
    elif sharpness >= _SHARP_GOOD:      bonus += 2.5
    elif sharpness >= _SHARP_SOFT_LOW:  bonus += 0.5
    else:                               bonus -= 2.0   # visible blur (but above hard limit)

    # ── Face coverage ─────────────────────────────────────────────────────────
    # Large face → good close-up / frontal shot → high engagement potential
    if face_ratio >= 0.12:    bonus += 4.0   # prominent face close-up
    elif face_ratio >= 0.05:  bonus += 2.5   # clear face, mid-range
    elif face_ratio >= 0.01:  bonus += 1.0   # face visible but small
    # face_ratio == 0: could be product close-up — neutral, no penalty

    # ── Exposure ──────────────────────────────────────────────────────────────
    if brightness < 35 or brightness > 225:
        bonus -= 3.0   # severe under/over-exposure

    return bonus


async def enrich_visual_scores(mp4: str, segs: list) -> None:
    """
    Enrich seg.score with a visual quality bonus for every valid segment.

    Extracts one frame at the segment midpoint and runs OpenCV analysis.
    Modifies segs in-place — call after enrich_audio_scores().

    Hard filter: sharpness < _SHARP_HARD_MIN → seg.valid = False (severe blur).

    Gracefully skips all scoring if opencv-python is not installed.
    """
    try:
        import cv2  # noqa: F401 — early check; actual use is in _analyse_frame
    except ImportError:
        logger.info("opencv-python not installed — visual scoring skipped (pip install opencv-python-headless)")
        return

    valid = [s for s in segs if s.valid]
    if not valid:
        return

    async def _one(seg) -> None:
        mid = (seg.start + seg.end) / 2
        async with _SEM_VISUAL:
            frame_path = await _extract_frame(mp4, mid)

        if not frame_path:
            return  # extraction failed — leave score unchanged

        try:
            stats = await asyncio.to_thread(_analyse_frame, frame_path)
        finally:
            try:
                os.remove(frame_path)
            except Exception:
                pass

        if not stats:
            return

        sharpness  = stats["sharpness"]
        face_ratio = stats["face_ratio"]
        brightness = stats["brightness"]

        # Hard filter: severely blurry frames not worth including
        if sharpness < _SHARP_HARD_MIN:
            seg.valid = False
            logger.debug(
                f"Visual hard-filter (severe blur) [{seg.start:.1f}-{seg.end:.1f}]"
                f" sharpness={sharpness:.0f}"
            )
            return

        bonus = _visual_bonus(sharpness, face_ratio, brightness)
        seg.score = round(seg.score + bonus, 2)
        logger.debug(
            f"Visual [{seg.start:.1f}-{seg.end:.1f}] "
            f"sharp={sharpness:.0f} face={face_ratio:.3f} bright={brightness:.0f} "
            f"bonus={bonus:+.1f} → score={seg.score:.1f}"
        )

    await asyncio.gather(*[_one(s) for s in valid])
    enriched = sum(1 for s in valid if s.valid)
    filtered  = len(valid) - enriched
    logger.info(
        f"Visual scoring complete: {enriched} enriched, {filtered} hard-filtered"
        f" ({len(valid)} total valid)"
    )


# ── Phase D: Claude visual semantic scoring ───────────────────────────────────

_BEDROCK_URL   = os.environ.get("LLM_BASE_URL", "http://10.190.0.214:8080/v1")
_VISION_MODEL  = os.environ.get("LLM_MODEL", "us.anthropic.claude-sonnet-4-6")
_BEDROCK_TOKEN = os.environ.get("LLM_API_KEY", "sk-orx-ukMXZXaPzL_Du1Xkcx3UuiSEjcf7TiXJ")

# Max concurrent Bedrock API calls — keeps cost predictable and avoids rate limits.
_SEM_SEMANTIC = asyncio.Semaphore(2)

# Circuit breaker: set True after first unrecoverable Bedrock error (invalid model, auth fail).
# Prevents wasting frame-extraction time on every segment when the service is misconfigured.
_semantic_disabled = False

# Failure counter: trip circuit breaker after 3 consecutive timeouts/exceptions.
_semantic_fail_count = 0
_SEMANTIC_FAIL_THRESHOLD = 3

# In-process pHash cache: phash_int → analysis result dict.
# Prevents duplicate API calls for visually identical/similar frames across segments.
_PHASH_CACHE: dict[int, dict] = {}
_PHASH_MAX_DISTANCE = 10   # Hamming distance threshold for "same frame"

_VISION_PROMPT = """你正在分析假发直播间的视频帧。请评估以下内容并以JSON格式返回。

评估项目：
1. wig_visible: 假发在画面中的清晰可见程度 (0-10，0=看不见，10=非常清晰占据主体)
2. is_closeup: 是否为近景特写（主播头部/产品占画面50%以上）true/false
3. is_demo: 是否正在演示佩戴过程（戴上/摘下/展示假发效果）true/false
4. facing_camera: 主播是否正对镜头（而非侧对或背对）true/false
5. product_quality: 画面呈现质量（光线、构图、产品展示完整性）(0-10)
6. angle_variety: 画面是否展示了非正面角度（侧面/背面/俯视）true/false
7. has_scene_context: 画面是否有场景感（非纯白背景/有生活场景）true/false
8. lighting_quality: 画面光线是否充足、均匀，不过暗或过曝 (0-10，0=曝光严重失调，10=光线完美)
9. motion_stability: 画面运动是否稳定，镜头是否有明显抖动 (0-10，0=严重抖动，10=完全稳定)

只返回JSON，不含其他内容：
{"wig_visible": 数字, "is_closeup": 布尔, "is_demo": 布尔, "facing_camera": 布尔, "product_quality": 数字, "angle_variety": 布尔, "has_scene_context": 布尔, "lighting_quality": 数字, "motion_stability": 数字}"""


def _semantic_bonus(result: dict) -> float:
    """
    Translate Claude vision analysis into a score addend.

    Scoring philosophy (centered at 0 for average content):
    - wig_visible 0–10 → (val-5)*1.2  [-6, +6]   core product presence
    - product_quality 0–10 → (val-5)*0.8  [-4, +4]  presentation multiplier
    - is_demo → +3.5 (demonstrating beats describing)
    - is_closeup → +4.0 / -0.5 (close-up detail = highest purchase intent driver)
    - facing_camera → +1.5 / -0.5 (direct engagement)
    - angle_variety → +3.0 (multi-angle = platform-recommended differentiation)
    - has_scene_context → +2.0 (scene context increases viewer retention)

    Typical range: -5 to +20.
    """
    bonus = 0.0
    bonus += (result.get("wig_visible",     5) - 5) * 1.2
    bonus += (result.get("product_quality", 5) - 5) * 0.8
    if result.get("is_demo"):
        bonus += 3.5
    if result.get("is_closeup"):
        bonus += 4.0   # raised from 2.5: detail closeup is the highest purchase driver
    else:
        bonus -= 0.5
    if result.get("facing_camera"):
        bonus += 1.5
    else:
        bonus -= 0.5
    if result.get("angle_variety"):
        bonus += 3.0
    if result.get("has_scene_context"):
        bonus += 2.0
    lighting = result.get("lighting_quality", 5)
    if lighting > 7:
        bonus += (lighting - 7) * 0.8   # max +2.4
    elif lighting < 4:
        bonus -= (4 - lighting) * 1.2   # max -4.8
    motion = result.get("motion_stability", 7)
    if motion < 5:
        bonus -= (5 - motion) * 1.5     # max -7.5
    elif motion > 7:
        bonus += (motion - 7) * 0.5     # max +1.5
    return round(bonus, 2)


def _phash_of_file(frame_path: str) -> int | None:
    """Compute perceptual hash of a JPEG. Returns int or None on failure."""
    try:
        import imagehash
        from PIL import Image
        return int(str(imagehash.phash(Image.open(frame_path))), 16)
    except Exception:
        return None


def _find_cached(phash_int: int) -> dict | None:
    """Return a cached analysis if a visually similar frame (Hamming ≤ threshold) exists."""
    try:
        import imagehash
    except ImportError:
        return None
    query = imagehash.hex_to_hash(format(phash_int, "016x"))
    for stored_int, stored_result in _PHASH_CACHE.items():
        stored = imagehash.hex_to_hash(format(stored_int, "016x"))
        if query - stored <= _PHASH_MAX_DISTANCE:
            return stored_result
    return None


async def _call_bedrock_vision(frame_paths: list[str]) -> dict | None:
    """
    Call Bedrock Claude Haiku with 1–2 JPEG frames.
    Returns parsed analysis dict or None on failure.
    """
    content = []
    for fp in frame_paths:
        try:
            with open(fp, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode()
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}
            })
        except Exception as e:
            logger.debug(f"Frame read failed {fp}: {e}")
    if not content:
        return None
    content.append({"type": "text", "text": _VISION_PROMPT})

    payload = {
        "model": _VISION_MODEL,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 250,
        "temperature": 0,
    }
    url = f"{_BEDROCK_URL}/chat/completions"
    try:
        import httpx
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                url, json=payload,
                headers={
                    "Authorization": f"Bearer {_BEDROCK_TOKEN}",
                    "Content-Type": "application/json",
                },
            )
        if resp.status_code != 200:
            logger.warning(f"LLM vision {resp.status_code}: {resp.text[:200]}")
            if resp.status_code in (400, 403, 404):
                global _semantic_disabled
                _semantic_disabled = True
                logger.error(
                    f"LLM vision permanently disabled (status {resp.status_code}). "
                    "Check LLM_MODEL and LLM_API_KEY."
                )
            return None
        raw = resp.json()["choices"][0]["message"]["content"]
        # raw_decode stops at end of first complete JSON object, ignoring trailing text
        try:
            start = raw.index("{")
            obj, _ = json.JSONDecoder().raw_decode(raw, start)
            return obj
        except (ValueError, json.JSONDecodeError):
            logger.warning(f"No JSON in vision response: {raw[:200]}")
    except Exception as e:
        logger.warning(f"Bedrock vision call failed: {e}")
        global _semantic_fail_count, _semantic_disabled
        _semantic_fail_count += 1
        if _semantic_fail_count >= _SEMANTIC_FAIL_THRESHOLD:
            _semantic_disabled = True
            logger.error(
                f"LLM vision circuit breaker tripped after {_semantic_fail_count} failures "
                "(timeouts/connection errors). Semantic scoring disabled for this session."
            )
    return None


async def enrich_semantic_scores(mp4: str, segs: list) -> None:
    """
    Enrich seg.score with Claude Haiku visual semantic analysis (Phase D).

    Extracts 2 frames per segment (at 33% and 66% of duration).
    pHash deduplication skips API calls for visually identical frames
    (e.g. same product shown across multiple segments of the same recording).

    Modifies segs in-place — call after enrich_visual_scores().

    Gracefully skips if:
      - AWS_BEARER_TOKEN_BEDROCK not set
      - imagehash / Pillow not installed  (pip install imagehash Pillow)
      - Any Bedrock API error (non-fatal, score left unchanged)
    """
    if not _BEDROCK_TOKEN:
        logger.info("Semantic scoring skipped: AWS_BEARER_TOKEN_BEDROCK not set")
        return

    if _semantic_disabled:
        logger.info("Semantic scoring skipped: circuit breaker tripped (Bedrock misconfigured)")
        return

    try:
        import imagehash   # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        logger.info("Semantic scoring skipped: pip install imagehash Pillow")
        return

    valid = [s for s in segs if s.valid]
    if not valid:
        return

    async def _one(seg) -> None:
        dur  = seg.end - seg.start
        ts1  = seg.start + dur * 0.33
        ts2  = seg.start + dur * 0.66

        # Extract up to 2 frames — _extract_frame manages its own _SEM_FRAME lock internally
        frame1 = await _extract_frame(mp4, ts1)
        frame2 = await _extract_frame(mp4, ts2) if dur > 3.0 else None
        frames = [f for f in [frame1, frame2] if f]
        if not frames:
            return

        try:
            phashes = [await asyncio.to_thread(_phash_of_file, fp) for fp in frames]

            # Cache lookup (primary key = first frame's hash)
            result = None
            if phashes[0] is not None:
                result = await asyncio.to_thread(_find_cached, phashes[0])

            if result is not None:
                logger.debug(f"Semantic cache hit [{seg.start:.1f}-{seg.end:.1f}]")
            else:
                async with _SEM_SEMANTIC:
                    result = await _call_bedrock_vision(frames)
                # Store all frame hashes → same result
                if result:
                    for ph in phashes:
                        if ph is not None:
                            _PHASH_CACHE[ph] = result

            if result:
                bonus = _semantic_bonus(result)
                seg.score = round(seg.score + bonus, 2)
                logger.debug(
                    f"Semantic [{seg.start:.1f}-{seg.end:.1f}] "
                    f"wig={result.get('wig_visible',0)} demo={result.get('is_demo')} "
                    f"closeup={result.get('is_closeup')} facing={result.get('facing_camera')} "
                    f"pq={result.get('product_quality',0)} bonus={bonus:+.1f} → score={seg.score:.1f}"
                )
        finally:
            for fp in frames:
                try:
                    os.remove(fp)
                except Exception:
                    pass

    await asyncio.gather(*[_one(s) for s in valid])
    logger.info(f"Semantic scoring complete: {len(valid)} segments processed")


# ── Phase 2: LLM text scoring ─────────────────────────────────────────────────
# Uses Bedrock Claude to assess narrative value of zero-keyword segments.
# Gracefully degrades to no-op when Bedrock is unavailable.

_LLM_TEXT_PROMOTE_THRESHOLD   = 5.0   # LLM score >= this rescues a zero-score segment
_LLM_TEXT_DISAGREE_THRESHOLD  = 4.0   # LLM vs keyword delta >= this → rule suggestion
_LLM_TEXT_SEMAPHORE           = asyncio.Semaphore(1)  # max concurrent Bedrock calls (keep 1 to reduce local pressure)

_LLM_TEXT_PROMPT = """\
你在分析假发直播间的转录文本片段。请判断该片段对于剪辑高光视频的叙事价值。

片段文本：{text}

以JSON返回（只返回JSON，不要其他内容）：
{{"narrative_role":"problem|wearing_demo|product_feature|social_proof|comfort|scene|conversion|filler","score":数字0-12,"reasoning":"一句话"}}

评分标准：
0-2: 纯填充/闲聊/无实质信息
3-4: 轻度相关（一般性描述）
5-7: 中度相关（使用场景/产品功能）
8-10: 高价值（痛点/演示/社交证明）
11-12: 极高价值（核心卖点/强烈转化信号）

加分维度（在0-12基础上综合考量）：
- 多角度展示：提到侧面/背面/360展示/转一圈 → 倾向高分
- 具体参数：提到重量/材质/克数/头围/具体数值 → 倾向高分
- 痛点解决：先点痛点（头大/发量少/显假）再给解法 → 倾向高分
- 真实口语：第一人称真实叙事，有具体时间/次数/细节动作 → 倾向高分
- 新潮趋势性（novelty signal）：内容涉及新款/新色/联名/限定/今年流行/风格名称（Y2K/法式/日系等），说明商品有时令或趋势属性 → 加2-3分"""

_NARRATIVE_TO_CATEGORY = {
    "problem":         "problem",
    "wearing_demo":    "wearing",
    "product_feature": "product",
    "social_proof":    "social_proof",
    "comfort":         "comfort",
    "scene":           "scene",
    "conversion":      "convert",
    "filler":          "neutral",
}


async def _call_bedrock_text(text: str) -> dict | None:
    """Call LLM to score a text segment. Returns parsed JSON or None."""
    import httpx
    llm_url   = os.environ.get("LLM_BASE_URL", "http://10.190.0.214:8080/v1")
    llm_key   = os.environ.get("LLM_API_KEY", "sk-orx-ukMXZXaPzL_Du1Xkcx3UuiSEjcf7TiXJ")
    llm_model = os.environ.get("LLM_MODEL", "us.anthropic.claude-sonnet-4-6")

    payload = {
        "model": llm_model,
        "messages": [
            {"role": "system", "content": "你是视频内容分析助手，专注于假发直播内容价值评估。"},
            {"role": "user", "content": _LLM_TEXT_PROMPT.format(text=text[:300])}
        ],
        "max_tokens": 150,
        "temperature": 0.1,
    }
    try:
        async with _LLM_TEXT_SEMAPHORE:
            async with httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(retries=1),
                http2=False, timeout=15.0
            ) as client:
                resp = await client.post(
                    f"{llm_url}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {llm_key}"},
                )
        if resp.status_code != 200:
            return None
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as e:
        logger.debug(f"LLM text score failed: {e}")
        return None


async def enrich_llm_text_scores(segs: list, recording_id: int | None = None) -> None:
    """
    Phase 2: For zero-score segments (reject_reason='zero_score' or score==0),
    call Bedrock Claude to assess narrative value.

    - If LLM score >= _LLM_TEXT_PROMOTE_THRESHOLD: mark segment valid, update score + category.
    - If keyword_score > 0 but LLM disagrees by >= _LLM_TEXT_DISAGREE_THRESHOLD:
      store a 'llm' rule_suggestion for user review.

    Modifies segs in-place. Silently skips on any Bedrock failure.
    """
    from db import DB_PATH

    zero_segs = [s for s in segs if s.score == 0 and not s.valid and s.reject_reason == "zero_score"]
    if not zero_segs:
        return

    logger.info(f"LLM text scoring: {len(zero_segs)} zero-score segments")

    suggestions_to_store = []

    async def _score_one(seg) -> None:
        result = await _call_bedrock_text(seg.text)
        if not result:
            return
        llm_score = float(result.get("score", 0))
        narrative_role = result.get("narrative_role", "filler")

        if llm_score >= _LLM_TEXT_PROMOTE_THRESHOLD:
            seg.valid = True
            seg.score = round(llm_score, 1)
            seg.category = _NARRATIVE_TO_CATEGORY.get(narrative_role, "neutral")
            seg.reject_reason = ""
            logger.debug(
                f"LLM promoted [{seg.start:.1f}-{seg.end:.1f}] "
                f"score={llm_score} role={narrative_role}: {seg.text[:40]}"
            )

        # Disagreement with keyword scoring: keyword scored > 0 but LLM scored low
        # (handled separately — for keyword-scored segments we don't call this function)

    await asyncio.gather(*[_score_one(s) for s in zero_segs])

    # Also check keyword-scored segments for LLM disagreement (sample up to 5 per call)
    kw_segs = [s for s in segs if s.score >= 6.0 and s.valid][:5]

    async def _check_disagreement(seg) -> None:
        result = await _call_bedrock_text(seg.text)
        if not result:
            return
        llm_score = float(result.get("score", 0))
        delta = seg.score - llm_score

        if delta >= _LLM_TEXT_DISAGREE_THRESHOLD:
            # LLM thinks this is worth much less than keywords suggest → suggest reduction
            from editor import _SCORES_EFFECTIVE, _KW_TO_CAT
            # Find the highest-scoring keyword in this segment
            best_kw, best_kw_score = None, 0.0
            for kw, sc in _SCORES_EFFECTIVE.items():
                if kw in seg.text and sc > best_kw_score:
                    best_kw, best_kw_score = kw, sc

            if best_kw:
                suggestions_to_store.append({
                    "source":          "llm",
                    "keyword":         best_kw,
                    "current_score":   best_kw_score,
                    "suggested_score": max(1.0, round(llm_score, 1)),
                    "reason":          f"LLM评分 {llm_score:.1f} vs 关键词评分 {seg.score:.1f}，差值 {delta:.1f}。LLM叙事判断：{result.get('reasoning','')[:80]}",
                    "evidence":        json.dumps({
                        "llm_score":     llm_score,
                        "keyword_score": seg.score,
                        "narrative_role": result.get("narrative_role"),
                        "reasoning":     result.get("reasoning", "")[:120],
                        "seg_text":      seg.text[:100],
                        "recording_id":  recording_id,
                    }),
                })

    await asyncio.gather(*[_check_disagreement(s) for s in kw_segs])

    if suggestions_to_store:
        try:
            import aiosqlite
            async with aiosqlite.connect(DB_PATH, timeout=60) as db:
                for s in suggestions_to_store:
                    # Don't overwrite already-resolved suggestions
                    async with db.execute(
                        "SELECT id FROM rule_suggestions WHERE keyword=? AND status IN ('accepted','rejected')",
                        (s["keyword"],),
                    ) as cur:
                        if await cur.fetchone():
                            continue
                    # Upsert pending llm suggestion for this keyword
                    await db.execute(
                        "DELETE FROM rule_suggestions WHERE keyword=? AND source='llm' AND status='pending'",
                        (s["keyword"],),
                    )
                    await db.execute("""
                        INSERT INTO rule_suggestions
                            (source, keyword, current_score, suggested_score, reason, evidence, status)
                        VALUES (?, ?, ?, ?, ?, ?, 'pending')
                    """, (
                        s["source"], s["keyword"], s["current_score"],
                        s["suggested_score"], s["reason"], s["evidence"],
                    ))
                await db.commit()
            logger.info(f"LLM text scorer: stored {len(suggestions_to_store)} rule suggestions")
        except Exception as e:
            logger.debug(f"LLM suggestion store failed: {e}")
