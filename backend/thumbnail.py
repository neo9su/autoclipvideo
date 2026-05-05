"""
Anime-style thumbnail generator.

Pipeline:
  1. ffmpeg extracts a raw frame from the clip
  2. Pillow composites anime-style overlays:
     - Gradient colour-grade (pastel/vibrant)
     - Scattered sparkle stars (code-drawn)
     - Large outlined title text with gradient fill (站酷快乐体)
     - Small subtitle pill (站酷小薇体)
     - Decorative corner accents
"""
import asyncio
import logging
import math
import os
import random
import tempfile
from typing import Optional

logger = logging.getLogger(__name__)

_ASSETS = os.path.join(os.path.dirname(__file__), "assets", "fonts")
_FONT_TITLE    = os.path.join(_ASSETS, "ZCOOLKuaiLe-Regular.ttf")
_FONT_SUBTITLE = os.path.join(_ASSETS, "ZCOOLXiaoWei-Regular.ttf")

# Fallback to system fonts if assets are missing
_SYS_FONTS = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/AssetsV2/com_apple_MobileAsset_Font8/"
    "4a418d1fa4860652a3241e8ee457806c8557fc64.asset/AssetData/Yuanti.ttc",
]

# ── Colour themes ─────────────────────────────────────────────────────────────
# Each theme: (grad_top RGBA, grad_bottom RGBA, title_grad_left RGB, title_grad_right RGB, outline RGB, pill_bg RGBA, pill_text RGB)
# Split into WARM_THEMES (for cool-toned images) and COOL_THEMES (for warm-toned images)
# so font always contrasts with the background.

_WARM_THEMES = [
    # Fiery orange-red
    ((255, 120,  40, 110), (200,  50,  10, 150), (255, 230, 160), (255, 140,  30), (180,  60,   0), (255, 120,  30, 200), (255, 255, 255)),
    # Vivid yellow-gold
    ((255, 220,  50, 110), (220, 150,  10, 150), (255, 255, 180), (255, 200,  30), (160, 110,   0), (255, 200,  40, 200), (255, 255, 255)),
    # Hot pink-red
    ((255,  80, 100, 110), (200,  20,  60, 150), (255, 200, 210), (255,  60, 100), (180,   0,  60), (255,  60, 100, 200), (255, 255, 255)),
]

_COOL_THEMES = [
    # Electric cyan-blue
    (( 40, 180, 255, 110), ( 10,  90, 220, 150), (200, 245, 255), ( 40, 200, 255), (  0,  90, 200), ( 30, 190, 255, 200), (255, 255, 255)),
    # Purple-violet
    ((160,  80, 255, 110), ( 80,  20, 200, 150), (230, 200, 255), (160,  80, 255), ( 80,   0, 180), (140,  60, 255, 200), (255, 255, 255)),
    # Mint green
    (( 60, 220, 180, 110), ( 20, 160, 120, 150), (190, 255, 230), ( 50, 220, 170), (  0, 130,  90), ( 40, 210, 160, 200), (255, 255, 255)),
]


def _image_warmth(img) -> float:
    """Return a warmth score for img (PIL RGB): >0 warm, <0 cool.
    Uses the R-B channel difference on a tiny downsampled version for speed.
    """
    tiny = img.convert("RGB").resize((32, 32))
    pixels = list(tiny.getdata())
    avg_r = sum(p[0] for p in pixels) / len(pixels)
    avg_b = sum(p[2] for p in pixels) / len(pixels)
    return avg_r - avg_b  # positive = warm, negative = cool


def _pick_theme(frame_path: str, rng: random.Random):
    """Choose a contrasting theme based on the frame's colour temperature."""
    from PIL import Image
    try:
        img = Image.open(frame_path)
        warmth = _image_warmth(img)
        # Warm image (R > B) → use cool-toned font theme
        # Cool image (B > R) → use warm-toned font theme
        pool = _COOL_THEMES if warmth > 8 else _WARM_THEMES
    except Exception:
        pool = _WARM_THEMES
    return rng.choice(pool)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_font(path: str, size: int):
    from PIL import ImageFont
    if os.path.exists(path):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    for fp in _SYS_FONTS:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _lerp_color(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(len(c1)))


def _draw_gradient_rect(img, x0, y0, x1, y1, color_top, color_bottom):
    """Vertical gradient fill over a rectangle."""
    from PIL import Image
    h = y1 - y0
    if h <= 0:
        return
    grad = Image.new("RGBA", (1, h))
    for y in range(h):
        grad.putpixel((0, y), _lerp_color(color_top, color_bottom, y / max(h - 1, 1)))
    grad = grad.resize((x1 - x0, h), Image.NEAREST)
    img.alpha_composite(grad, (x0, y0))


def _draw_sparkles(draw, rng, w, h, count=22):
    """Draw scattered 4-point star sparkles. Size scales with image width."""
    from PIL import ImageDraw
    scale = w / 1080  # scale relative to original 1080p design
    r_min, r_max = int(4 * scale), int(14 * scale)
    dot = max(2, int(2 * scale))
    for _ in range(count):
        cx = rng.randint(20, w - 20)
        cy = rng.randint(20, h - 20)
        r  = rng.randint(r_min, r_max)
        alpha = rng.randint(160, 255)
        color = (255, 255, 255, alpha)
        pts_h = [(cx - r, cy), (cx, cy - r // 3), (cx + r, cy), (cx, cy + r // 3)]
        pts_v = [(cx, cy - r), (cx + r // 3, cy), (cx, cy + r), (cx - r // 3, cy)]
        draw.polygon(pts_h, fill=color)
        draw.polygon(pts_v, fill=color)
        draw.ellipse([cx - dot, cy - dot, cx + dot, cy + dot], fill=(255, 255, 255, 255))


def _draw_corner_accents(draw, w, h, color):
    """Thin L-shaped lines at all four corners. Size scales with image width."""
    scale = w / 1080
    L, T = int(40 * scale), max(3, int(3 * scale))
    corners = [
        [(0, T // 2), (L, T // 2), (T // 2, T // 2), (T // 2, L)],
        [(w - L, T // 2), (w, T // 2), (w - T // 2, T // 2), (w - T // 2, L)],
        [(0, h - T // 2), (L, h - T // 2), (T // 2, h - L), (T // 2, h - T // 2)],
        [(w - L, h - T // 2), (w, h - T // 2), (w - T // 2, h - L), (w - T // 2, h - T // 2)],
    ]
    for a, b, c, d in corners:
        draw.line([a, b], fill=color, width=T)
        draw.line([c, d], fill=color, width=T)


def _text_with_outline(draw, pos, text, font, fill, outline, outline_width=6):
    """Draw text with a solid outline for legibility."""
    x, y = pos
    for dx in range(-outline_width, outline_width + 1, 2):
        for dy in range(-outline_width, outline_width + 1, 2):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=outline)
    draw.text(pos, text, font=font, fill=fill)


def _gradient_text(base_img, draw, pos, text, font, color_l, color_r, outline, outline_width=6, alpha=255):
    """
    Render text with a left→right gradient fill.
    alpha: overall opacity of the text (0-255).
    """
    from PIL import Image, ImageDraw
    bbox = font.getbbox(text)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    if tw <= 0 or th <= 0:
        draw.text(pos, text, font=font, fill=color_l)
        return

    # Outline pass
    x, y = pos
    out_alpha = min(255, int(alpha * 0.9))  # slightly more opaque outline for legibility
    for dx in range(-outline_width, outline_width + 1, 2):
        for dy in range(-outline_width, outline_width + 1, 2):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=outline[:3] + (out_alpha,))

    # Gradient text layer
    pad = outline_width + 4
    layer = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.text((pad - bbox[0], pad - bbox[1]), text, font=font, fill=(255, 255, 255, 255))

    # Horizontal gradient colourisation with alpha scaling
    grad = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
    for px in range(tw + pad * 2):
        t = px / max(tw + pad * 2 - 1, 1)
        c = _lerp_color(color_l[:3] + (255,), color_r[:3] + (255,), t)
        for py in range(th + pad * 2):
            src_a = layer.getpixel((px, py))[3]
            if src_a > 0:
                grad.putpixel((px, py), c[:3] + (int(src_a * alpha / 255),))

    base_img.alpha_composite(grad, (x - pad + bbox[0], y - pad + bbox[1]))


def _draw_pill(draw, img, text, font, cx, y, bg_color, text_color, pad_x=28, pad_h=16):
    """Rounded rectangle pill label centred at (cx, y)."""
    from PIL import Image, ImageDraw
    bbox = font.getbbox(text)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    pw, ph = tw + pad_x * 2, th + pad_h * 2
    pill = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    pd = ImageDraw.Draw(pill)
    r = ph // 2
    pd.rounded_rectangle([0, 0, pw - 1, ph - 1], radius=r, fill=bg_color)
    pd.text((pad_x - bbox[0], pad_h - bbox[1]), text, font=font, fill=text_color)
    img.alpha_composite(pill, (cx - pw // 2, y))


# ── Frame extraction ──────────────────────────────────────────────────────────

async def _extract_frame(mp4_path: str, seek: float, out_jpg: str, target_w: int = 1080, target_h: int = 1920) -> bool:
    """
    Extract one frame at `seek` seconds.  If the source is smaller than
    target_w x target_h it is upscaled with lanczos so the compositor
    always receives a full-resolution base image.
    """
    # First pass: extract at native resolution
    cmd = [
        "ffmpeg", "-y", "-ss", f"{seek:.3f}", "-i", mp4_path,
        "-frames:v", "1",
        "-q:v", "1",
        out_jpg,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    await proc.communicate()
    if proc.returncode != 0 or not os.path.exists(out_jpg) or os.path.getsize(out_jpg) == 0:
        return False

    # Upscale if the source is low-resolution (e.g. old 240p recordings)
    try:
        from PIL import Image, ImageFilter, ImageEnhance
        img = Image.open(out_jpg)
        w, h = img.size
        if w < target_w or h < target_h:
            scale = max(target_w / w, target_h / h)
            new_w, new_h = int(w * scale), int(h * scale)
            img = img.convert("RGB").resize((new_w, new_h), Image.LANCZOS)
            # Crop to target (centre)
            left = (new_w - target_w) // 2
            top  = (new_h - target_h) // 2
            img = img.crop((left, top, left + target_w, top + target_h))
            # Mild sharpening to recover upscale softness
            img = img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=60, threshold=3))
            img.save(out_jpg, "JPEG", quality=95)
            logger.debug(f"Upscaled frame {w}x{h} → {target_w}x{target_h} for {os.path.basename(mp4_path)}")
    except Exception as e:
        logger.debug(f"Frame upscale skipped: {e}")

    return True


async def _get_duration(mp4_path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", mp4_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    stdout, _ = await proc.communicate()
    try:
        return float(stdout.strip())
    except (ValueError, TypeError):
        return 10.0


# ── Main compositor ───────────────────────────────────────────────────────────

def _composite(frame_path: str, out_path: str, title: str, subtitle: str, seed: int,
               anime_overlay_path: str = None):
    from PIL import Image, ImageDraw, ImageFilter, ImageEnhance

    rng = random.Random(seed)
    theme = _pick_theme(frame_path, rng)
    grad_top, grad_bottom, title_l, title_r, title_outline, pill_bg, pill_text = theme

    # Use native frame resolution — no upscaling to avoid distortion
    _raw = Image.open(frame_path).convert("RGBA")
    W, H = _raw.size

    # Scale factor relative to the 1080p design baseline (width)
    _scale = W / 1080

    base = _raw

    # Mild contrast boost only — avoid oversaturation/warmth shift
    base_rgb = base.convert("RGB")
    base_rgb = ImageEnhance.Contrast(base_rgb).enhance(1.08)
    # No Color enhance — preserve original skin/hair tones
    base = base_rgb.convert("RGBA")

    # Blur only bottom 18% of frame (text area) — keeps person area sharp
    blur_start = int(H * 0.82)
    blur_band = base.crop((0, blur_start, W, H)).filter(ImageFilter.GaussianBlur(radius=6))
    base.paste(blur_band, (0, blur_start))

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    # Bottom gradient veil for text readability
    _draw_gradient_rect(overlay, 0, H * 3 // 4, W, H,
                        (0, 0, 0, 0), (0, 0, 0, 160))

    # NO top colour tone strip — it shifts warmth and obscures the subject

    base.alpha_composite(overlay)

    draw = ImageDraw.Draw(base, "RGBA")

    # Sparkles
    spark_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    spark_draw  = ImageDraw.Draw(spark_layer)
    _draw_sparkles(spark_draw, rng, W, H, count=28)
    base.alpha_composite(spark_layer)

    # Corner accents
    _draw_corner_accents(draw, W, H, (255, 255, 255, 180))

    # ── Title text ────────────────────────────────────────────────────────────
    font_title = _load_font(_FONT_TITLE, int(148 * _scale))
    font_sub   = _load_font(_FONT_SUBTITLE, int(68 * _scale))

    ALPHA = 204  # 80% opacity

    # Wrap title if too long (max ~8 chars per line)
    chars_per_line = 8
    if len(title) <= chars_per_line:
        lines = [title]
    else:
        mid = len(title) // 2
        lines = [title[:mid], title[mid:]]

    line_h = int(180 * _scale)
    total_text_h = len(lines) * line_h
    text_top = H - int(540 * _scale) - total_text_h

    for i, line in enumerate(lines):
        bbox = font_title.getbbox(line)
        tw = bbox[2] - bbox[0]
        tx = (W - tw) // 2 - bbox[0]
        ty = text_top + i * line_h - bbox[1]
        _gradient_text(base, draw, (tx, ty), line,
                        font_title, title_l, title_r,
                        title_outline, outline_width=int(8 * _scale), alpha=ALPHA)

    # ── Subtitle pill ─────────────────────────────────────────────────────────
    pill_bg_a = pill_bg[:3] + (int(pill_bg[3] * 0.8),) if len(pill_bg) == 4 else pill_bg[:3] + (168,)
    pill_text_a = pill_text[:3] + (ALPHA,) if len(pill_text) == 3 else pill_text[:3] + (ALPHA,)
    _draw_pill(draw, base, subtitle, font_sub,
               cx=W // 2, y=H - int(310 * _scale),
               bg_color=pill_bg_a, text_color=pill_text_a)

    # ── Decorative divider line ───────────────────────────────────────────────
    line_y = H - int(360 * _scale)
    draw.line([(W // 2 - int(180 * _scale), line_y), (W // 2 + int(180 * _scale), line_y)],
              fill=(255, 255, 255, 100), width=max(2, int(2 * _scale)))

    base = base.convert("RGB")
    base.save(out_path, "JPEG", quality=96, optimize=True, subsampling=0)
    return True


# ── Public API ────────────────────────────────────────────────────────────────

_SCHEME_SUBTITLES = {
    "种草": "点击查看同款",
    "催单": "直播间同价 点小黄车下单",
    "产品介绍": "了解更多详情",
    "教学": "手把手教你变美",
}

# Cover schemes for the 3-candidate cover generator
# Each: (title, subtitle, frame_offset_fraction)
COVER_SCHEMES = [
    {"id": "volume",   "title": "发量直接翻倍", "subtitle": "细软塌必看",     "offset_frac": 0.25},
    {"id": "transform","title": "换个发型像换脸","subtitle": "真的不一样",     "offset_frac": 0.55},
    {"id": "rescue",   "title": "细软塌救星",   "subtitle": "发量少的看这个", "offset_frac": 0.75},
]


async def generate_cover_candidates(
    mp4_path: str,
    group_id: int,
    out_dir: str,
) -> list[str]:
    """
    Generate 3 cover candidates from different frames of mp4_path.
    Each scheme uses a different video timestamp and marketing title.
    ComfyUI anime overlay is NOT used (causes ghosting on real footage).

    Returns list of output JPEG paths (may be fewer than 3 on partial failure).
    """
    import os as _os
    _os.makedirs(out_dir, exist_ok=True)
    duration = await _get_duration(mp4_path)

    results = []
    for scheme in COVER_SCHEMES:
        seek = max(1.0, duration * scheme["offset_frac"])
        out_path = _os.path.join(out_dir, f"cover_{group_id}_{scheme['id']}.jpg")
        frame_tmp = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as _tf:
                frame_tmp = _tf.name
            ok = await _extract_frame(mp4_path, seek, frame_tmp)
            if not ok:
                logger.warning(f"Cover frame extraction failed: {mp4_path} seek={seek}")
                continue
            seed = hash(mp4_path + scheme["id"]) & 0xFFFFFF
            await asyncio.get_running_loop().run_in_executor(
                None, _composite, frame_tmp, out_path,
                scheme["title"], scheme["subtitle"], seed, None
            )
            if _os.path.exists(out_path) and _os.path.getsize(out_path) > 0:
                results.append(out_path)
        except Exception as e:
            logger.error(f"Cover generation error for scheme {scheme['id']}: {e}")
        finally:
            if frame_tmp:
                try:
                    _os.remove(frame_tmp)
                except Exception:
                    pass

    return results


async def generate_thumbnail(mp4_path: str, offset: Optional[float] = None,
                              title: str = "假发变美瞬间",
                              subtitle: str = "点击查看同款",
                              scheme_type: str = "种草") -> Optional[str]:
    """
    Generate an anime-style thumbnail for `mp4_path`.

    Pipeline:
      1. ffmpeg extracts a raw frame
      2. ComfyUI converts it to anime illustration style (falls back to raw frame)
      3. Pillow composites title/subtitle/sparkles overlays

    Returns path to the output JPEG, or None on failure.
    """
    # scheme_type overrides subtitle if subtitle is still the default
    if subtitle == "点击查看同款" and scheme_type in _SCHEME_SUBTITLES:
        subtitle = _SCHEME_SUBTITLES[scheme_type]

    out = mp4_path.replace(".mp4", "_thumb.jpg")

    duration = await _get_duration(mp4_path)
    seek = offset if offset is not None else max(1.0, duration * 0.3)

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        frame_path = tmp.name
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        anime_path = tmp.name
    comfy_input = None  # must be initialized before try so finally can reference it

    try:
        # Step 1: extract raw frame
        ok = await _extract_frame(mp4_path, seek, frame_path)
        if not ok:
            logger.warning(f"Frame extraction failed for {mp4_path}")
            return None

        # Step 2: anime-style via ComfyUI (best-effort style overlay, not base frame)
        # Raw frame is always the base for sharpness; ComfyUI adds anime colour grading.
        anime_overlay = None
        try:
            from comfyui_client import anime_img2img, health_check
            if await health_check():
                seed = hash(mp4_path) & 0xFFFFFF
                from PIL import Image as _PIL
                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as _tf:
                    comfy_input = _tf.name
                _img = _PIL.open(frame_path).convert("RGB")
                _img = _img.resize((576, 1024), _PIL.LANCZOS)
                _img.save(comfy_input, "JPEG", quality=88)
                converted = await anime_img2img(comfy_input, anime_path, seed=seed, timeout=120)
                if converted and os.path.exists(anime_path) and os.path.getsize(anime_path) > 0:
                    anime_overlay = anime_path   # used as 35% style overlay, NOT base
                    logger.debug(f"ComfyUI anime overlay ready for {mp4_path}")
                else:
                    logger.debug("ComfyUI conversion failed, using raw frame only")
            else:
                logger.debug("ComfyUI unavailable, using raw frame only")
        except Exception as e:
            logger.warning(f"ComfyUI step skipped: {e}")

        # Step 3: composite — raw frame (sharp) + optional anime overlay + title/subtitle
        seed = hash(mp4_path) & 0xFFFFFF
        await asyncio.get_running_loop().run_in_executor(
            None, _composite, frame_path, out, title, subtitle, seed, anime_overlay
        )

        if os.path.exists(out) and os.path.getsize(out) > 0:
            logger.debug(f"Thumbnail generated: {out}")
            return out
        return None

    except Exception as e:
        logger.error(f"Thumbnail generation error for {mp4_path}: {e}")
        return None
    finally:
        for p in (frame_path, anime_path, comfy_input):
            if p:
                try:
                    os.remove(p)
                except Exception:
                    pass
