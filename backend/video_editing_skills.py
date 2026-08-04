"""Reusable video editing skill helpers for director/qianchuan composition.

The helpers in this module are intentionally deterministic and dependency-light:
- short WAV sound effects are generated locally when no asset is present;
- transition names are normalized to FFmpeg's stable xfade vocabulary;
- visual-skill decisions are expressed as metadata so GPU and local fallback paths can
  degrade safely when a renderer does not support a specific effect.
"""
from __future__ import annotations

import logging
import math
import wave
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)

ASSET_AUDIO_DIR = Path(__file__).parent / "assets" / "audio"
DEFAULT_SFX_GAIN_DB = -15.0

STABLE_TRANSITIONS = {
    "fade",
    "dissolve",
    "wipeleft",
    "wiperight",
    "slideleft",
    "slideright",
    "smoothleft",
    "smoothright",
    "circleopen",
    "fadeblack",
    "fadewhite",
    "distance",
    "zoomin",
}

TRANSITION_ALIASES = {
    "cut": "fade",
    "xfade": "fade",
    "crossfade": "fade",
    "blur": "fade",
    "push": "smoothleft",
    "pushleft": "smoothleft",
    "pushright": "smoothright",
    "flash": "fadewhite",
    "whiteflash": "fadewhite",
    "phone_zoom": "zoomin",
}

DETAIL_SCENE_TYPES = {
    "detail",
    "product",
    "wearing",
    "demonstration",
    "comparison",
    "product_proof",
    "tryon_result",
}

EMPHASIS_SCENE_TYPES = {
    "hook",
    "result",
    "conversion",
    "cta",
    "promotion",
    "urgency",
    "result_hook",
}


def normalize_transition_name(name: Optional[str], fallback: str = "fade") -> str:
    """Return a stable FFmpeg xfade transition name with safe fallback."""
    raw = (name or fallback or "fade").strip().lower()
    normalized = TRANSITION_ALIASES.get(raw, raw)
    if normalized in STABLE_TRANSITIONS:
        return normalized
    logger.info("Unsupported transition %r; using %s", name, fallback)
    return TRANSITION_ALIASES.get(fallback, fallback if fallback in STABLE_TRANSITIONS else "fade")


def _write_tone_wav(path: Path, *, frequency: float, duration: float, amplitude: float) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 44100
    frames = max(1, int(sample_rate * duration))
    with wave.open(str(path), "w") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        for frame_index in range(frames):
            attack = min(1.0, frame_index / max(1.0, sample_rate * 0.010))
            release = min(1.0, (frames - frame_index) / max(1.0, sample_rate * 0.045))
            envelope = max(0.0, min(attack, release))
            sample = int(amplitude * envelope * 32767 * math.sin(2 * math.pi * frequency * frame_index / sample_rate))
            wav.writeframesraw(sample.to_bytes(2, byteorder="little", signed=True))
    return str(path)


def ensure_sfx_asset(kind: str = "soft_click", preferred_path: Optional[str] = None) -> Optional[str]:
    """Return an existing/generated short SFX path, or None if generation fails.

    Missing assets must never fail composition. Callers can skip cues when None is
    returned and keep producing the video without sound effects.
    """
    target = Path(preferred_path) if preferred_path else ASSET_AUDIO_DIR / f"edit_{kind}.wav"
    if target.exists() and target.stat().st_size > 1000:
        return str(target)
    try:
        if kind == "transition_swoosh":
            return _write_tone_wav(target, frequency=720.0, duration=0.16, amplitude=0.16)
        if kind == "emphasis_pop":
            return _write_tone_wav(target, frequency=1280.0, duration=0.075, amplitude=0.18)
        return _write_tone_wav(target, frequency=980.0, duration=0.060, amplitude=0.15)
    except Exception as exc:
        logger.warning("SFX asset unavailable for %s: %s", kind, exc)
        return None


def build_edit_sound_cues(
    clips: Sequence[Dict],
    *,
    transition_duration: float,
    existing_cues: Optional[Iterable[Dict]] = None,
    sfx_overrides: Optional[Dict[str, str]] = None,
) -> List[Dict]:
    """Create subtle transition/emphasis sound cues for final audio mixing."""
    cues: List[Dict] = []
    for cue in existing_cues or []:
        if isinstance(cue, dict):
            cues.append(dict(cue))

    sfx_overrides = sfx_overrides or {}
    transition_sfx = ensure_sfx_asset("transition_swoosh", sfx_overrides.get("transition"))
    emphasis_sfx = ensure_sfx_asset("emphasis_pop", sfx_overrides.get("emphasis"))

    cursor = 0.0
    for index, clip in enumerate(clips):
        duration = max(0.0, float(clip.get("duration") or 0.0))
        scene_type = str(clip.get("scene_type") or "")
        text = str(clip.get("script_text") or "")

        if emphasis_sfx and (scene_type in EMPHASIS_SCENE_TYPES or any(token in text for token in ("显白", "蓬松", "自然", "细节", "发缝"))):
            cues.append({
                "time": round(cursor + 0.18, 2),
                "sfx_path": emphasis_sfx,
                "gain_db": DEFAULT_SFX_GAIN_DB,
                "reason": "keyword_emphasis",
            })

        if transition_sfx and index < len(clips) - 1:
            cue_time = max(0.0, cursor + duration - max(0.05, transition_duration * 0.55))
            cues.append({
                "time": round(cue_time, 2),
                "sfx_path": transition_sfx,
                "gain_db": DEFAULT_SFX_GAIN_DB - 2,
                "reason": "transition",
            })

        cursor += max(0.0, duration - (transition_duration if index < len(clips) - 1 else 0.0))

    return cues[:80]


def should_enable_pip(scene_type: Optional[str], edit_actions: Optional[Iterable[Dict]] = None) -> bool:
    """Return True when a clip should receive the local crop-zoom PIP detail window."""
    if (scene_type or "") in DETAIL_SCENE_TYPES:
        return True
    for action in edit_actions or []:
        if isinstance(action, dict) and str(action.get("type") or "") in {"detail_zoom", "crop_zoom", "pip_detail"}:
            return True
    return False


def build_pip_filter(width: int, height: int) -> str:
    """Build a conservative top-right picture-in-picture crop zoom filtergraph.

    The crop uses the upper/right subject-safe area and overlays a small framed
    window below the keyword pop zone, leaving bottom subtitles unobstructed.
    """
    pip_width = max(260, min(360, int(width * 0.30)))
    margin_x = max(42, int(width * 0.05))
    margin_y = max(190, int(height * 0.12))
    crop_w = "iw*0.42"
    crop_h = "ih*0.34"
    crop_x = "iw*0.46"
    crop_y = "ih*0.18"
    return (
        f",split=2[main][pip_src];"
        f"[pip_src]crop={crop_w}:{crop_h}:{crop_x}:{crop_y},"
        f"scale={pip_width}:-1:flags=lanczos,"
        f"pad=iw+14:ih+14:7:7:color=white@0.88[pip_box];"
        f"[main][pip_box]overlay=x=W-w-{margin_x}:y={margin_y}:"
        f"enable='gte(t,0.35)'"
    )
