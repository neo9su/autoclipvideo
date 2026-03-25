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

# ── Anime colour themes ────────────────────────────────────────────────────────
# Each theme: (grad_top RGBA, grad_bottom RGBA, title_grad_left, title_grad_right, outline, pill_bg, pill_text)
_THEMES = [
    # Sakura bloom — warm pink, soft rose bottom
    ((255, 190, 220, 130), (220,  80, 130, 160), (255, 230, 245), (255, 120, 190), (200,  40, 110), (255, 100, 170, 210), (255, 255, 255)),
    # Peach sunshine — golden orange top, warm coral bottom
    ((255, 220, 150, 130), (240, 120,  60, 160), (255, 250, 200), (255, 180,  60), (180,  80,   0), (255, 160,  50, 210), (255, 255, 255)),
    # Candy sky — cheerful sky blue, warm lemon bottom
    ((160, 230, 255, 120), (100, 180, 255, 150), (220, 248, 255), (80,  200, 255), ( 30, 120, 200), (60,  190, 255, 210), (255, 255, 255)),
    # Warm lemon — bright yellow, soft apricot bottom
    ((255, 240, 130, 120), (255, 190,  80, 150), (255, 255, 200), (255, 210,  60), (160, 120,   0), (255, 210,  60, 210), (255, 255, 255)),
    # Spring mint — fresh green top, warm lime bottom
    ((180, 255, 210, 120), (100, 210, 140, 150), (220, 255, 235), (80,  230, 160), ( 20, 140,  80), (70,  220, 150, 210), (255, 255, 255)),
]


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
    """Draw scattered 4-point star sparkles."""
    from PIL import ImageDraw
    for _ in range(count):
        cx = rng.randint(20, w - 20)
        cy = rng.randint(20, h - 20)
        r  = rng.randint(4, 14)
        alpha = rng.randint(160, 255)
        color = (255, 255, 255, alpha)
        # 4-point star via two thin diamonds
        pts_h = [(cx - r, cy), (cx, cy - r // 3), (cx + r, cy), (cx, cy + r // 3)]
        pts_v = [(cx, cy - r), (cx + r // 3, cy), (cx, cy + r), (cx - r // 3, cy)]
        draw.polygon(pts_h, fill=color)
        draw.polygon(pts_v, fill=color)
        # Tiny centre dot
        draw.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=(255, 255, 255, 255))


def _draw_corner_accents(draw, w, h, color):
    """Thin L-shaped lines at all four corners."""
    L, T = 40, 3
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


def _gradient_text(base_img, draw, pos, text, font, color_l, color_r, outline, outline_width=6):
    """
    Render text with a left→right gradient fill by:
      1. Drawing text on a temp RGBA layer with the left colour
      2. Masking it with a horizontal gradient
      3. Compositing onto base_img
    """
    from PIL import Image, ImageDraw
    # Measure text
    bbox = font.getbbox(text)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    if tw <= 0 or th <= 0:
        draw.text(pos, text, font=font, fill=color_l)
        return

    # Outline pass (on base draw)
    x, y = pos
    for dx in range(-outline_width, outline_width + 1, 2):
        for dy in range(-outline_width, outline_width + 1, 2):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=outline + (255,))

    # Gradient text layer
    pad = outline_width + 4
    layer = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.text((pad - bbox[0], pad - bbox[1]), text, font=font, fill=(255, 255, 255, 255))

    # Horizontal gradient mask colourisation
    grad = Image.new("RGBA", (tw + pad * 2, th + pad * 2), (0, 0, 0, 0))
    for px in range(tw + pad * 2):
        t = px / max(tw + pad * 2 - 1, 1)
        c = _lerp_color(color_l + (255,), color_r + (255,), t)
        for py in range(th + pad * 2):
            if layer.getpixel((px, py))[3] > 0:
                grad.putpixel((px, py), c[:3] + (layer.getpixel((px, py))[3],))

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

async def _extract_frame(mp4_path: str, seek: float, out_jpg: str) -> bool:
    # Extract at full 4K — _composite uses this as-is for a crisp base frame
    cmd = [
        "ffmpeg", "-y", "-ss", f"{seek:.3f}", "-i", mp4_path,
        "-frames:v", "1",
        "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,"
               "pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
        "-q:v", "2", out_jpg,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    await proc.communicate()
    return proc.returncode == 0 and os.path.exists(out_jpg) and os.path.getsize(out_jpg) > 0


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

def _composite(frame_path: str, out_path: str, title: str, subtitle: str, seed: int):
    from PIL import Image, ImageDraw, ImageFilter

    rng = random.Random(seed)
    theme = rng.choice(_THEMES)
    grad_top, grad_bottom, title_l, title_r, title_outline, pill_bg, pill_text = theme

    W, H = 1080, 1920  # 2K portrait (9:16)

    # Base frame
    base = Image.open(frame_path).convert("RGBA").resize((W, H), Image.LANCZOS)

    # Subtle blur on lower portion to make text pop
    blur_band = base.crop((0, H // 2, W, H)).filter(ImageFilter.GaussianBlur(radius=3))
    base.paste(blur_band, (0, H // 2))

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    # Bottom gradient veil — lighter to keep overall warmth
    _draw_gradient_rect(overlay, 0, H * 3 // 4, W, H,
                        (0, 0, 0, 0), (0, 0, 0, 140))

    # Top colour tone strip
    _draw_gradient_rect(overlay, 0, 0, W, H // 5,
                        grad_top, (0, 0, 0, 0))

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
    font_title = _load_font(_FONT_TITLE, 148)
    font_sub   = _load_font(_FONT_SUBTITLE, 68)

    # Wrap title if too long (max ~8 chars per line for 1440px)
    chars_per_line = 8
    if len(title) <= chars_per_line:
        lines = [title]
    else:
        mid = len(title) // 2
        lines = [title[:mid], title[mid:]]

    line_h = 180
    total_text_h = len(lines) * line_h
    text_top = H - 520 - total_text_h

    for i, line in enumerate(lines):
        bbox = font_title.getbbox(line)
        tw = bbox[2] - bbox[0]
        tx = (W - tw) // 2 - bbox[0]
        ty = text_top + i * line_h - bbox[1]
        _gradient_text(base, draw, (tx, ty), line,
                        font_title, title_l, title_r,
                        title_outline, outline_width=8)

    # ── Subtitle pill ─────────────────────────────────────────────────────────
    _draw_pill(draw, base, subtitle, font_sub,
               cx=W // 2, y=H - 300,
               bg_color=pill_bg, text_color=pill_text)

    # ── Decorative divider line ───────────────────────────────────────────────
    line_y = H - 340
    draw.line([(W // 2 - 180, line_y), (W // 2 + 180, line_y)],
              fill=(255, 255, 255, 120), width=2)

    base = base.convert("RGB")
    base.save(out_path, "JPEG", quality=92, optimize=True)
    return True


# ── Public API ────────────────────────────────────────────────────────────────

_SCHEME_SUBTITLES = {
    "种草": "点击查看同款",
    "催单": "直播间同价 点小黄车下单",
    "产品介绍": "了解更多详情",
    "教学": "手把手教你变美",
}


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

    try:
        # Step 1: extract raw frame
        ok = await _extract_frame(mp4_path, seek, frame_path)
        if not ok:
            logger.warning(f"Frame extraction failed for {mp4_path}")
            return None

        # Step 2: anime-style conversion via ComfyUI (best-effort)
        # SD1.5 requires ≤576×1024 input; downscale the 4K frame before sending.
        # The 4K raw frame is kept as the crisp background for _composite regardless.
        base_frame = frame_path   # always use 4K raw as base (crisp background)
        comfy_input = None
        try:
            from comfyui_client import anime_img2img, health_check
            if await health_check():
                seed = hash(mp4_path) & 0xFFFFFF
                # Downscale 4K → ComfyUI-safe resolution before img2img
                from PIL import Image as _PIL
                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as _tf:
                    comfy_input = _tf.name
                _img = _PIL.open(frame_path).convert("RGB")
                _img = _img.resize((576, 1024), _PIL.LANCZOS)
                _img.save(comfy_input, "JPEG", quality=88)
                converted = await anime_img2img(comfy_input, anime_path, seed=seed, timeout=120)
                if converted and os.path.exists(anime_path) and os.path.getsize(anime_path) > 0:
                    # Use ComfyUI anime output as base; _composite will resize to 4K
                    base_frame = anime_path
                    logger.debug(f"ComfyUI anime conversion done for {mp4_path}")
                else:
                    logger.debug("ComfyUI conversion failed, using 4K raw frame")
            else:
                logger.debug("ComfyUI unavailable, using 4K raw frame")
        except Exception as e:
            logger.warning(f"ComfyUI step skipped: {e}")

        # Step 3: composite title/subtitle overlays
        seed = hash(mp4_path) & 0xFFFFFF
        await asyncio.get_event_loop().run_in_executor(
            None, _composite, base_frame, out, title, subtitle, seed
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
