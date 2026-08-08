"""Qianchuan video learning and quality feedback module.

Extracts learnable patterns from reference videos and produces quality scores
with feedback-driven improvement suggestions for the next iteration.

## Architecture

-   `analyze_video()` reads a video analysis directory (1fps frames, timepoint
    frames, hero.jpg, spectrogram.jpg) and calls the LLM through the shared
    `llm_client.llm_post()` path (global semaphore, retries, timeout).

-   `score_quality()` computes a weighted 5‑dimension quality score:

    === "Weights"
        | Dimension  | Weight | Evidence source                      |
        |------------|--------|--------------------------------------|
        | visual     | 0.25   | hero.jpg, 1fps frames, shot variety  |
        | audio      | 0.20   | spectrogram.jpg, volume analysis     |
        | semantic   | 0.20   | LLM analysis, keyword relevance      |
        | structural | 0.20   | segment count, duration distribution |
        | conversion | 0.15   | CTA presence, audience fit, selling  |

    The overall score is `sum(dim.score * dim.weight)` clamped to [0, 100].
    Each dimension carries a dictionary of evidence and suggestions so that
    callers can surface *why* a score was computed.

-   `aggregate_feedback()` reads existing `qianchuan_score` / `qianchuan_review`
    / `qianchuan_segments` values (possibly old JSON) and synthesises improvement
    suggestions for the next editing round.

-   Serialization helpers (`serialize_score`, `deserialize_score`, etc.)
    produce/consume the JSON‑compatible dicts already stored in the database
    columns without altering the schema contract in `qianchuan_schema.py`.

## GPU / Media Validation

The module delegates media validation to `qianchuan_quality.check_qianchuan_video_quality()`.
When a remote GPU `job_id` is available the quality gate is applied; when it is
unavailable the module returns a diagnostic *degraded* result instead of
silently faking a pass.

## Degradation Policy

| Condition                    | Behaviour                                       |
|------------------------------|-------------------------------------------------|
| Directory missing            | Return empty analysis with `material_errors`    |
| Partial frame set            | Analyse whatever is present; note missing count |
| LLM call fails (all retries) | Fallback to structural-only analysis            |
| LLM returns non‑JSON         | Extract whatever fields parse; fill defaults    |
| GPU / remote quality fails   | `validated=False` with diagnostic message       |
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from llm_client import llm_post

# ---------------------------------------------------------------------------
# Dataclasses / type contracts
# ---------------------------------------------------------------------------


@dataclass
class HookAnalysis:
    """Analysis of the first 3 seconds (hook)."""

    hook_type: str = "unknown"
    effectiveness: str = "unknown"
    visual_elements: List[str] = field(default_factory=list)
    audio_elements: List[str] = field(default_factory=list)
    text_overlay: bool = False


@dataclass
class VisualStyle:
    """Visual style description."""

    dominant_colors: List[str] = field(default_factory=list)
    lighting: str = "unknown"
    shot_types: List[str] = field(default_factory=list)
    text_overlay_style: str = "none"
    composition: str = "unknown"


@dataclass
class AudioRhythm:
    """Audio and rhythm analysis."""

    bpm_estimate: Optional[int] = None
    energy_level: str = "unknown"
    has_background_music: bool = False
    has_sfx: bool = False
    speech_pace: str = "unknown"


@dataclass
class ConversionElement:
    """A single conversion-oriented element."""

    element_type: str = ""
    description: str = ""
    strength: str = "neutral"


@dataclass
class AudienceAdaptation:
    """Audience targeting signals."""

    primary_audience: str = "unknown"
    pain_points_addressed: List[str] = field(default_factory=list)
    trust_signals: List[str] = field(default_factory=list)


@dataclass
class ReusablePattern:
    """A pattern worth reusing in future videos."""

    pattern: str = ""
    category: str = ""
    confidence: float = 0.0


@dataclass
class VideoAnalysis:
    """Structured reference video analysis result.

    Every field has a reasonable default so that partial LLM output or a
    degraded analysis can still be serialised without crashing.
    """

    structure_description: str = ""
    segments: List[Dict[str, Any]] = field(default_factory=list)
    hook_analysis: HookAnalysis = field(default_factory=HookAnalysis)
    visual_style: VisualStyle = field(default_factory=VisualStyle)
    audio_rhythm: AudioRhythm = field(default_factory=AudioRhythm)
    conversion_elements: List[ConversionElement] = field(default_factory=list)
    audience_adaptation: AudienceAdaptation = field(default_factory=AudienceAdaptation)
    reusable_patterns: List[ReusablePattern] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    improvement_suggestions: List[str] = field(default_factory=list)

    # Diagnostics
    material_errors: List[str] = field(default_factory=list)
    llm_raw: Optional[str] = None
    llm_error: Optional[str] = None


@dataclass
class DimensionScore:
    """Single dimension score with evidence and suggestions."""

    score: float = 0.0
    weight: float = 0.20
    evidence: Dict[str, Any] = field(default_factory=dict)
    suggestions: List[str] = field(default_factory=list)


@dataclass
class QualityScore:
    """Aggregated 5‑dimension quality score (0‑100)."""

    visual: DimensionScore = field(default_factory=lambda: DimensionScore(weight=0.25))
    audio: DimensionScore = field(default_factory=lambda: DimensionScore(weight=0.20))
    semantic: DimensionScore = field(default_factory=lambda: DimensionScore(weight=0.20))
    structural: DimensionScore = field(default_factory=lambda: DimensionScore(weight=0.20))
    conversion: DimensionScore = field(default_factory=lambda: DimensionScore(weight=0.15))

    overall: float = 0.0
    validated: bool = False
    validation_details: List[str] = field(default_factory=list)
    degradation_reasons: List[str] = field(default_factory=list)


@dataclass
class FeedbackSignal:
    """Aggregate learning signal from past iterations."""

    iteration_count: int = 0
    score_trend: List[float] = field(default_factory=list)
    common_praises: List[str] = field(default_factory=list)
    common_issues: List[str] = field(default_factory=list)
    improvement_rules: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Default weights (can be overridden)
# ---------------------------------------------------------------------------

DEFAULT_WEIGHTS: Dict[str, float] = {
    "visual": 0.25,
    "audio": 0.20,
    "semantic": 0.20,
    "structural": 0.20,
    "conversion": 0.15,
}

# ---------------------------------------------------------------------------
# Helper: scan a video analysis directory
# ---------------------------------------------------------------------------

_MATERIAL_ITEMS = (
    ("1fps_dir", "1fps", True),
    ("hero_path", "hero.jpg", False),
    ("spectrogram_path", "spectrogram.jpg", False),
)


def _scan_materials(directory: str) -> Tuple[Dict[str, Any], List[str]]:
    """Scan *directory* for expected material files; return (found, errors).

    Parameters
    ----------
    directory : str
        Path to a per‑video analysis directory.

    Returns
    -------
    found : dict
        Absolute paths keyed by material name (``1fps_dir``, ``hero_path``,
        ``spectrogram_path``). Missing optional items are ``None``; missing
        required items are empty strings.
    errors : list[str]
        Human‑readable error messages for each missing item.
    """
    materials: Dict[str, Any] = {}
    errors: List[str] = []

    base = Path(directory)
    if not base.is_dir():
        return {}, [f"analysis directory does not exist: {directory}"]

    for key, rel, required in _MATERIAL_ITEMS:
        candidate = base / rel
        if required and not candidate.exists():
            errors.append(f"required material missing: {rel}")
            materials[key] = ""
        elif candidate.exists():
            materials[key] = str(candidate)
        else:
            materials[key] = None

    # Additional: scan 1fps frames if the dir exists
    fps_dir = materials.get("1fps_dir")
    if fps_dir and os.path.isdir(fps_dir):
        frames = sorted(Path(fps_dir).glob("*.jpg"))
        materials["1fps_count"] = len(frames)
        materials["1fps_frames"] = [str(p) for p in frames[:64]]
    else:
        materials["1fps_count"] = 0
        materials["1fps_frames"] = []

    # Timepoint frames: look for numeric-named jpg files in root
    timepoint_frames = sorted(
        p for p in base.glob("*.jpg") if p.name.split(".")[0].replace(".", "").isdigit()
    )
    materials["timepoint_frames"] = [str(p) for p in timepoint_frames[:32]]
    materials["timepoint_count"] = len(timepoint_frames)

    return materials, errors


# ---------------------------------------------------------------------------
# LLM analysis prompt & parsing
# ---------------------------------------------------------------------------

_ANALYSIS_SYSTEM_PROMPT = """You are a Qianchuan (千川) video analysis expert specialised in e-commerce short-video ads.
Analyse the reference video material information provided and return a JSON object with the following structure:

```json
{
  "structure_description": "string describing the overall video structure and pacing",
  "segments": [
    {"start_s": 0.0, "end_s": 3.0, "type": "result_hook|pain_point|product_proof|tryon_result|cta", "description": "...", "key_frames": "..."}
  ],
  "hook_analysis": {
    "hook_type": "result|pain|curiosity|shock|question",
    "effectiveness": "high|medium|low",
    "visual_elements": ["..."],
    "audio_elements": ["..."],
    "text_overlay": true|false
  },
  "visual_style": {
    "dominant_colors": ["#hex", ...],
    "lighting": "natural|studio|warm|cool|mixed",
    "shot_types": ["closeup", "mid", "full", ...],
    "text_overlay_style": "bold|subtle|none",
    "composition": "centered|rule_of_thirds|dynamic"
  },
  "audio_rhythm": {
    "bpm_estimate": null,
    "energy_level": "high|medium|low",
    "has_background_music": true|false,
    "has_sfx": true|false,
    "speech_pace": "fast|moderate|slow"
  },
  "conversion_elements": [
    {"element_type": "cta|trust_proof|discount|scarcity|social_proof", "description": "...", "strength": "strong|moderate|weak"}
  ],
  "audience_adaptation": {
    "primary_audience": "产后妈妈群|职场白领群|中老年刚需群|时尚变美群",
    "pain_points_addressed": ["..."],
    "trust_signals": ["..."]
  },
  "reusable_patterns": [
    {"pattern": "...", "category": "hook|transition|cta|visual|audio", "confidence": 0.0}
  ],
  "risks": ["..."],
  "improvement_suggestions": ["..."]
}
```

Rules:
- Base your analysis purely on the material information provided; do NOT invent frame details that aren't referenced.
- If materials are incomplete, note that in the description but still provide your best analysis.
- Escaped JSON only; no markdown code fences in the response."""


def _build_analysis_user_prompt(materials: Dict[str, Any]) -> str:
    """Construct a concise user prompt from scanned material metadata."""
    lines: List[str] = [
        "Analyse the following Qianchuan reference video materials:",
        "",
    ]

    if materials.get("hero_path"):
        lines.append(f"- Hero/cover image present: {materials['hero_path']}")

    fps_count = materials.get("1fps_count", 0)
    lines.append(f"- 1fps sample frames available: {fps_count}")

    tp_count = materials.get("timepoint_count", 0)
    if tp_count:
        timepoints = [Path(p).stem for p in materials.get("timepoint_frames", [])]
        lines.append(f"- Timepoint keyframes at: {', '.join(timepoints)}s")

    if materials.get("spectrogram_path"):
        lines.append("- Audio spectrogram present")
    else:
        lines.append("- No audio spectrogram available")

    lines.append("")
    lines.append("Provide the complete JSON analysis of this video based on the material information above.")

    return "\n".join(lines)


def _parse_analysis_json(raw: str) -> Tuple[Dict[str, Any], Optional[str]]:
    """Best‑effort JSON parse with fallback.

    Returns ``(parsed_dict, error_or_none)``.  ``parsed_dict`` is never None
    but may be an empty dict on catastrophic failure.
    """
    if not raw or not raw.strip():
        return {}, "empty LLM response"

    # Try direct parse first
    try:
        return json.loads(raw), None
    except json.JSONDecodeError:
        pass

    # Try extracting from code fences (```json ... ```)
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if match:
        try:
            return json.loads(match.group(1)), None
        except json.JSONDecodeError:
            pass

    # Try to find the first { and last }
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start : end + 1]), None
        except json.JSONDecodeError:
            pass

    return {}, f"failed to parse LLM response as JSON ({raw[:200]})"


def _dict_to_hook_analysis(hook: Dict[str, Any]) -> HookAnalysis:
    return HookAnalysis(
        hook_type=str(hook.get("hook_type", "unknown")),
        effectiveness=str(hook.get("effectiveness", "unknown")),
        visual_elements=_safe_str_list(hook.get("visual_elements")),
        audio_elements=_safe_str_list(hook.get("audio_elements")),
        text_overlay=bool(hook.get("text_overlay", False)),
    )


def _dict_to_visual_style(style: Dict[str, Any]) -> VisualStyle:
    return VisualStyle(
        dominant_colors=_safe_str_list(style.get("dominant_colors")),
        lighting=str(style.get("lighting", "unknown")),
        shot_types=_safe_str_list(style.get("shot_types")),
        text_overlay_style=str(style.get("text_overlay_style", "none")),
        composition=str(style.get("composition", "unknown")),
    )


def _dict_to_audio_rhythm(audio: Dict[str, Any]) -> AudioRhythm:
    bpm = audio.get("bpm_estimate")
    try:
        bpm = int(bpm) if bpm is not None else None
    except (TypeError, ValueError):
        bpm = None
    return AudioRhythm(
        bpm_estimate=bpm,
        energy_level=str(audio.get("energy_level", "unknown")),
        has_background_music=bool(audio.get("has_background_music", False)),
        has_sfx=bool(audio.get("has_sfx", False)),
        speech_pace=str(audio.get("speech_pace", "unknown")),
    )


def _dict_to_conversion_elements(elements: Any) -> List[ConversionElement]:
    if not isinstance(elements, list):
        return []
    return [
        ConversionElement(
            element_type=str(item.get("element_type", "")),
            description=str(item.get("description", "")),
            strength=str(item.get("strength", "neutral")),
        )
        for item in elements
        if isinstance(item, dict)
    ]


def _dict_to_audience_adaptation(aud: Dict[str, Any]) -> AudienceAdaptation:
    return AudienceAdaptation(
        primary_audience=str(aud.get("primary_audience", "unknown")),
        pain_points_addressed=_safe_str_list(aud.get("pain_points_addressed")),
        trust_signals=_safe_str_list(aud.get("trust_signals")),
    )


def _dict_to_reusable_patterns(patterns: Any) -> List[ReusablePattern]:
    if not isinstance(patterns, list):
        return []
    result: List[ReusablePattern] = []
    for item in patterns:
        if not isinstance(item, dict):
            continue
        conf = item.get("confidence", 0.0)
        try:
            conf = float(conf)
        except (TypeError, ValueError):
            conf = 0.0
        result.append(
            ReusablePattern(
                pattern=str(item.get("pattern", "")),
                category=str(item.get("category", "")),
                confidence=max(0.0, min(1.0, conf)),
            )
        )
    return result


def _safe_str_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    return []


# ---------------------------------------------------------------------------
# Public API: analyse a reference video
# ---------------------------------------------------------------------------


async def analyze_video(
    directory: str,
    *,
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 3000,
) -> VideoAnalysis:
    """Analyse the reference video in *directory* using the LLM.

    Parameters
    ----------
    directory : str
        Path to a per‑video analysis directory containing 1fps frames,
        hero.jpg, spectrogram.jpg, and timepoint frames.
    model : str or None
        Override the default LLM model.
    temperature : float
        LLM sampling temperature.
    max_tokens : int
        Maximum output tokens.

    Returns
    -------
    VideoAnalysis
        Structured analysis.  On LLM failure the result contains structural
        metadata from scanned materials only; ``llm_error`` documents why.
    """
    materials, material_errors = _scan_materials(directory)

    analysis = VideoAnalysis(material_errors=material_errors)

    if material_errors and materials.get("1fps_count", 0) == 0:
        # No usable visual data at all; return degraded result immediately
        analysis.risks.append("No usable visual materials found in analysis directory")
        return analysis

    user_prompt = _build_analysis_user_prompt(materials)
    messages = [
        {"role": "system", "content": _ANALYSIS_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    raw = await llm_post(
        messages,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
    )

    if raw is None:
        analysis.llm_error = "LLM call failed after all retries"
        analysis.risks.append("LLM analysis unavailable — structural-only fallback")
        return analysis

    analysis.llm_raw = raw
    parsed, parse_error = _parse_analysis_json(raw)

    if parse_error:
        analysis.llm_error = parse_error
        if not parsed:
            analysis.risks.append("LLM response could not be parsed; structural-only fallback")
            return analysis

    # Populate from parsed dict (best-effort)
    analysis.structure_description = str(parsed.get("structure_description", ""))
    analysis.segments = _safe_segments(parsed.get("segments"))
    analysis.hook_analysis = _dict_to_hook_analysis(parsed.get("hook_analysis") or {})
    analysis.visual_style = _dict_to_visual_style(parsed.get("visual_style") or {})
    analysis.audio_rhythm = _dict_to_audio_rhythm(parsed.get("audio_rhythm") or {})
    analysis.conversion_elements = _dict_to_conversion_elements(parsed.get("conversion_elements"))
    analysis.audience_adaptation = _dict_to_audience_adaptation(parsed.get("audience_adaptation") or {})
    analysis.reusable_patterns = _dict_to_reusable_patterns(parsed.get("reusable_patterns"))
    analysis.risks.extend(_safe_str_list(parsed.get("risks")))
    analysis.improvement_suggestions = _safe_str_list(parsed.get("improvement_suggestions"))

    return analysis


def _safe_segments(segments: Any) -> List[Dict[str, Any]]:
    if not isinstance(segments, list):
        return []
    result: List[Dict[str, Any]] = []
    for seg in segments:
        if isinstance(seg, dict):
            result.append({
                "start_s": seg.get("start_s", 0.0),
                "end_s": seg.get("end_s", 0.0),
                "type": seg.get("type", ""),
                "description": seg.get("description", ""),
                "key_frames": seg.get("key_frames", ""),
            })
    return result


# ---------------------------------------------------------------------------
# 5‑Dimension quality scoring
# ---------------------------------------------------------------------------


def score_quality(
    analysis: Optional[VideoAnalysis] = None,
    quality_result: Optional[Dict[str, Any]] = None,
    *,
    weights: Optional[Dict[str, float]] = None,
) -> QualityScore:
    """Compute a 5‑dimension quality score (0–100).

    Parameters
    ----------
    analysis : VideoAnalysis or None
        LLM‑produced analysis (used for semantic / structural / conversion
        evidence).
    quality_result : dict or None
        Output from ``qianchuan_quality.check_qianchuan_video_quality()``.
        When present it provides GPU‑validated constraints that feed into
        visual and audio dimensions.
    weights : dict or None
        Dimension weights.  Defaults to ``DEFAULT_WEIGHTS``.

    Returns
    -------
    QualityScore
        Aggregated score with per‑dimension evidence.

    Notes
    -----
    – If *quality_result* contains ``hard_gate_failures`` the ``validated``
      flag is ``False`` and the failures are included in ``validation_details``.
    – If *quality_result* is ``None`` the ``validated`` flag remains ``False``
      (degraded mode) and the reason is noted.
    """
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    score = QualityScore()

    # -- validation gate from qianchuan_quality.py ------------------------------
    if quality_result is None:
        score.validated = False
        score.validation_details.append("no quality_result provided (non-GPU / degraded mode)")
    else:
        score.validated = quality_result.get("ok", False)
        failures = quality_result.get("hard_gate_failures") or quality_result.get("errors") or []
        score.validation_details = [str(f) for f in failures]
        if not score.validated:
            score.degradation_reasons.extend(score.validation_details)

    # -- material availability flags -------------------------------------------
    mat_errors = analysis.material_errors if analysis else []
    has_hero = analysis is not None and not any(
        "hero.jpg" in e for e in mat_errors
    )
    has_frames = analysis is not None and not any(
        "1fps" in e for e in mat_errors
    )
    has_spectrogram = analysis is not None and not any(
        "spectrogram" in e for e in mat_errors
    )

    # === visual (0.25) ===
    visual = _score_visual(analysis, quality_result, has_hero, has_frames, mat_errors)
    visual.weight = w["visual"]
    score.visual = visual

    # === audio (0.20) ===
    audio = _score_audio(analysis, quality_result, has_spectrogram, mat_errors)
    audio.weight = w["audio"]
    score.audio = audio

    # === semantic (0.20) ===
    semantic = _score_semantic(analysis)
    semantic.weight = w["semantic"]
    score.semantic = semantic

    # === structural (0.20) ===
    structural = _score_structural(analysis)
    structural.weight = w["structural"]
    score.structural = structural

    # === conversion (0.15) ===
    conv = _score_conversion(analysis)
    conv.weight = w["conversion"]
    score.conversion = conv

    # === aggregate ===
    dims = [score.visual, score.audio, score.semantic, score.structural, score.conversion]
    raw_total = sum(d.score * d.weight for d in dims)
    score.overall = round(max(0.0, min(100.0, raw_total)), 1)

    if not score.validated:
        score.degradation_reasons.append("quality validation not passed — score is informational only")

    return score


def _score_visual(
    analysis: Optional[VideoAnalysis],
    quality_result: Optional[Dict[str, Any]],
    has_hero: bool,
    has_frames: bool,
    mat_errors: List[str],
) -> DimensionScore:
    evidence: Dict[str, Any] = {}
    suggestions: List[str] = []
    score = 50.0  # neutral baseline

    if not has_frames and not has_hero:
        evidence["material_status"] = "no visual materials"
        score = 10.0
        suggestions.append("Provide hero.jpg or 1fps frames for visual assessment")
        return DimensionScore(score=score, evidence=evidence, suggestions=suggestions)

    # Start from baseline, adjust upward based on what's available
    if has_hero:
        evidence["hero_image"] = "present"
        score += 15.0

    if has_frames:
        evidence["1fps_frames"] = "present"
        score += 10.0

    if mat_errors:
        evidence["material_warnings"] = mat_errors
        score -= 5.0 * len([e for e in mat_errors if "optional" not in e])

    if analysis:
        style = analysis.visual_style
        evidence["lighting"] = style.lighting
        evidence["shot_types"] = style.shot_types
        evidence["composition"] = style.composition

        if style.lighting != "unknown":
            score += 5.0
        if len(style.shot_types) >= 2:
            score += 5.0
        if style.composition != "unknown":
            score += 5.0

        if len(style.shot_types) < 2:
            suggestions.append("Increase shot type variety for visual interest")

    if quality_result and quality_result.get("ok"):
        score += 5.0

    score = max(0.0, min(100.0, score))
    return DimensionScore(score=round(score, 1), evidence=evidence, suggestions=suggestions)


def _score_audio(
    analysis: Optional[VideoAnalysis],
    quality_result: Optional[Dict[str, Any]],
    has_spectrogram: bool,
    mat_errors: List[str],
) -> DimensionScore:
    evidence: Dict[str, Any] = {}
    suggestions: List[str] = []
    score = 50.0

    if has_spectrogram:
        evidence["spectrogram"] = "present"
        score += 10.0
    else:
        evidence["spectrogram"] = "missing"
        suggestions.append("Generate audio spectrogram for quality assessment")

    if analysis and analysis.audio_rhythm.energy_level != "unknown":
        rhythm = analysis.audio_rhythm
        evidence["energy_level"] = rhythm.energy_level
        evidence["speech_pace"] = rhythm.speech_pace
        evidence["has_bgm"] = rhythm.has_background_music
        evidence["has_sfx"] = rhythm.has_sfx

        if rhythm.energy_level in ("medium", "high"):
            score += 8.0
        if rhythm.speech_pace in ("moderate", "fast"):
            score += 5.0
        if rhythm.has_sfx:
            score += 5.0
        if rhythm.bpm_estimate:
            score += 3.0

        if rhythm.energy_level == "low":
            suggestions.append("Increase audio energy with faster BGM")
        if not rhythm.has_sfx:
            suggestions.append("Add keyword cue sound effects")

    if quality_result and quality_result.get("ok"):
        score += 5.0

    score = max(0.0, min(100.0, score))
    return DimensionScore(score=round(score, 1), evidence=evidence, suggestions=suggestions)


def _score_semantic(analysis: Optional[VideoAnalysis]) -> DimensionScore:
    evidence: Dict[str, Any] = {}
    suggestions: List[str] = []
    score = 50.0

    if not analysis or analysis.llm_error:
        evidence["analysis_available"] = False
        return DimensionScore(score=score, evidence=evidence, suggestions=["Run LLM analysis for semantic scoring"])

    evidence["analysis_available"] = True
    desc = analysis.structure_description
    if desc and len(desc) > 20:
        score += 15.0
    if analysis.hook_analysis.effectiveness in ("high", "medium"):
        score += 10.0
    if analysis.hook_analysis.effectiveness == "low":
        suggestions.append("Strengthen the hook — first 3s need to grab attention harder")

    aud = analysis.audience_adaptation
    if aud.primary_audience != "unknown":
        evidence["primary_audience"] = aud.primary_audience
        score += 5.0
    if aud.pain_points_addressed:
        score += 5.0
        evidence["pain_points"] = aud.pain_points_addressed

    score = max(0.0, min(100.0, score))
    return DimensionScore(score=round(score, 1), evidence=evidence, suggestions=suggestions)


def _score_structural(analysis: Optional[VideoAnalysis]) -> DimensionScore:
    evidence: Dict[str, Any] = {}
    suggestions: List[str] = []
    score = 50.0

    if not analysis:
        return DimensionScore(score=score, evidence=evidence, suggestions=["No analysis available for structural scoring"])

    segments = analysis.segments
    evidence["segment_count"] = len(segments)
    if 4 <= len(segments) <= 8:
        score += 15.0
    elif len(segments) >= 3:
        score += 8.0
    elif len(segments) > 8:
        score += 5.0
        suggestions.append("Reduce segment count for cleaner pacing")

    if len(segments) < 3:
        suggestions.append("Increase segment count to at least 3–5 for proper pacing")

    # Check for Qainchuan 5-scene structure coverage
    scene_types = {s.get("type") for s in segments}
    expected = {"result_hook", "pain_point", "product_proof", "tryon_result", "cta"}
    coverage = len(scene_types & expected)
    evidence["scene_coverage"] = coverage
    score += coverage * 3.0

    if coverage < 3:
        suggestions.append("Cover more Qianchuan scene types (hook, pain, proof, result, CTA)")

    score = max(0.0, min(100.0, score))
    return DimensionScore(score=round(score, 1), evidence=evidence, suggestions=suggestions)


def _score_conversion(analysis: Optional[VideoAnalysis]) -> DimensionScore:
    evidence: Dict[str, Any] = {}
    suggestions: List[str] = []
    score = 50.0

    if not analysis:
        return DimensionScore(score=score, evidence=evidence, suggestions=["No analysis available for conversion scoring"])

    elements = analysis.conversion_elements
    evidence["element_count"] = len(elements)
    if len(elements) >= 3:
        score += 10.0
    elif len(elements) >= 1:
        score += 5.0
    else:
        suggestions.append("Add at least 3 conversion elements (CTA, trust proof, social proof)")

    strong = sum(1 for e in elements if e.strength == "strong")
    evidence["strong_elements"] = strong
    if strong >= 2:
        score += 10.0
    elif strong >= 1:
        score += 5.0

    has_cta = any(e.element_type == "cta" for e in elements)
    evidence["has_cta"] = has_cta
    if has_cta:
        score += 5.0
    else:
        suggestions.append("Include an explicit CTA (call-to-action) element")

    has_trust = any(e.element_type == "trust_proof" for e in elements)
    if has_trust:
        score += 5.0
    else:
        suggestions.append("Add trust proof element (brand authorization, real result)")

    if analysis.audience_adaptation.trust_signals:
        score += 3.0

    score = max(0.0, min(100.0, score))
    return DimensionScore(score=round(score, 1), evidence=evidence, suggestions=suggestions)


# ---------------------------------------------------------------------------
# Feedback closed-loop
# ---------------------------------------------------------------------------


async def aggregate_feedback(
    existing_reviews: Optional[List[Dict[str, Any]]] = None,
    existing_scores: Optional[List[float]] = None,
    existing_segments: Optional[List[Dict[str, Any]]] = None,
) -> FeedbackSignal:
    """Aggregate learning signals from past iterations.

    Parameters
    ----------
    existing_reviews : list[dict] or None
        Raw ``qianchuan_review`` values from past iterations.  Each element is
        a parsed JSON object (dict).  Bad JSON / old formats are skipped with
        a warning.
    existing_scores : list[float] or None
        Raw ``qianchuan_score`` values.
    existing_segments : list[dict] or None
        Raw ``qianchuan_segments`` values.

    Returns
    -------
    FeedbackSignal
        Aggregated signal with suggestions for the next editing iteration.
    """
    signal = FeedbackSignal()
    reviews = _normalise_reviews(existing_reviews, signal.warnings)
    scores = _normalise_scores(existing_scores, signal.warnings)
    segments = _normalise_segments(existing_segments, signal.warnings)

    signal.iteration_count = len(reviews)
    signal.score_trend = scores

    if not reviews and not scores:
        signal.warnings.append("no usable feedback data found — first iteration")
        return signal

    # Extract common praises and issues from review dicts
    praises: Dict[str, int] = {}
    issues: Dict[str, int] = {}

    for review in reviews:
        review_issues = review.get("issues") or []
        if isinstance(review_issues, list):
            for issue in review_issues:
                if isinstance(issue, dict):
                    severity = issue.get("severity", "")
                    detail = issue.get("detail", "")
                    selling = issue.get("selling_point", "")
                    text = f"{selling}: {detail}".strip(": ")
                    if text and text != ": ":
                        if severity in ("error", "critical"):
                            issues[text] = issues.get(text, 0) + 1
                        if severity in ("pass", "info"):
                            praises[text] = praises.get(text, 0) + 1

    if praises:
        signal.common_praises = sorted(praises, key=lambda k: -praises[k])[:5]
    if issues:
        signal.common_issues = sorted(issues, key=lambda k: -issues[k])[:5]

    # Generate improvement rules
    rules: List[str] = []

    if signal.score_trend:
        if len(signal.score_trend) >= 2 and signal.score_trend[-1] < signal.score_trend[-2]:
            rules.append("Score declined — review last iteration changes for regression")
        if all(s < 70 for s in signal.score_trend) and len(signal.score_trend) >= 2:
            rules.append("Scores consistently below 70 — consider a fundamental structure change")

    if signal.common_issues:
        for issue in signal.common_issues[:3]:
            rules.append(f"Fix recurring issue: {issue[:120]}")

    if signal.common_praises:
        for praise in signal.common_praises[:2]:
            rules.append(f"Preserve strength: {praise[:120]}")

    # Segment-level learning
    if segments:
        accepted = sum(1 for s in segments if isinstance(s, dict) and s.get("ok", True))
        rejected = len(segments) - accepted
        if rejected > 0:
            rules.append(f"Past iterations had {rejected} rejected segments — tighten relevance matching")

    signal.improvement_rules = rules
    return signal


def _normalise_reviews(
    reviews: Optional[List[Any]], warnings: List[str]
) -> List[Dict[str, Any]]:
    """Safely normalise a list of review values into dicts."""
    if not reviews:
        return []
    result: List[Dict[str, Any]] = []
    for item in reviews:
        if isinstance(item, dict):
            result.append(item)
            continue
        if isinstance(item, str):
            try:
                parsed = json.loads(item)
                if isinstance(parsed, dict):
                    result.append(parsed)
                elif isinstance(parsed, list):
                    result.extend(r for r in parsed if isinstance(r, dict))
            except json.JSONDecodeError:
                warnings.append(f"skipping unparseable review JSON: {item[:80]}")
        elif isinstance(item, list):
            for sub in item:
                if isinstance(sub, dict):
                    result.append(sub)
                elif isinstance(sub, str):
                    try:
                        parsed = json.loads(sub)
                        if isinstance(parsed, dict):
                            result.append(parsed)
                    except json.JSONDecodeError:
                        pass
    return result


def _normalise_scores(
    scores: Optional[List[Any]], warnings: List[str]
) -> List[float]:
    """Safely normalise a list of score values into floats."""
    if not scores:
        return []
    result: List[float] = []
    for s in scores:
        try:
            result.append(float(s))
        except (TypeError, ValueError):
            warnings.append(f"skipping non-numeric score: {s!r}")
    return result


def _normalise_segments(
    segments: Optional[List[Any]], warnings: List[str]
) -> List[Dict[str, Any]]:
    """Safely normalise a list of segment values into dicts."""
    if not segments:
        return []
    result: List[Dict[str, Any]] = []
    for s in segments:
        if isinstance(s, dict):
            result.append(s)
            continue
        if isinstance(s, str):
            try:
                parsed = json.loads(s)
                if isinstance(parsed, dict):
                    result.append(parsed)
                elif isinstance(parsed, list):
                    result.extend(r for r in parsed if isinstance(r, dict))
            except json.JSONDecodeError:
                warnings.append(f"skipping unparseable segment JSON: {s[:80]}")
    return result


# ---------------------------------------------------------------------------
# Serialization helpers (compatible with qianchuan_schema.py columns)
# ---------------------------------------------------------------------------


def serialize_score(score: QualityScore) -> Dict[str, Any]:
    """Convert a ``QualityScore`` to a JSON‑compatible dict for ``qianchuan_score``.

    The returned dict is designed to coexist with the existing REAL column
    (which holds a raw float) — API consumers should check whether the value
    is a number or an object.
    """
    return {
        "_format": "qianchuan_score_v1",
        "overall": score.overall,
        "dimensions": {
            "visual": _serialize_dimension(score.visual),
            "audio": _serialize_dimension(score.audio),
            "semantic": _serialize_dimension(score.semantic),
            "structural": _serialize_dimension(score.structural),
            "conversion": _serialize_dimension(score.conversion),
        },
        "validated": score.validated,
        "validation_details": score.validation_details,
        "degradation_reasons": score.degradation_reasons,
    }


def _serialize_dimension(dim: DimensionScore) -> Dict[str, Any]:
    return {
        "score": dim.score,
        "weight": dim.weight,
        "evidence": dim.evidence,
        "suggestions": dim.suggestions,
    }


def deserialize_score(data: Any) -> Optional[QualityScore]:
    """Parse a stored ``qianchuan_score`` value into a ``QualityScore``.

    Accepts:
    - A float/int (legacy format) → returns a ``QualityScore`` with only
      ``overall`` populated.
    - A dict with ``_format == "qianchuan_score_v1"`` → full deserialization.
    - A JSON string → parsed then treated as above.
    - ``None`` → returns ``None``.

    Returns ``None`` on unparseable input (callers should handle gracefully).
    """
    if data is None:
        return None

    if isinstance(data, (int, float)):
        score = QualityScore()
        score.overall = round(float(data), 1)
        return score

    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            return None

    if not isinstance(data, dict):
        return None

    if data.get("_format") != "qianchuan_score_v1":
        # Legacy dict format — try to extract overall
        overall = data.get("overall", data.get("score", data.get("qianchuan_score")))
        if overall is not None:
            try:
                score = QualityScore(overall=round(float(overall), 1))
                return score
            except (TypeError, ValueError):
                pass
        return None

    score = QualityScore(overall=float(data.get("overall", 0)))
    dims = data.get("dimensions") or {}
    score.visual = _deserialize_dimension(dims.get("visual"))
    score.audio = _deserialize_dimension(dims.get("audio"))
    score.semantic = _deserialize_dimension(dims.get("semantic"))
    score.structural = _deserialize_dimension(dims.get("structural"))
    score.conversion = _deserialize_dimension(dims.get("conversion"))
    score.validated = bool(data.get("validated", False))
    score.validation_details = _safe_str_list(data.get("validation_details"))
    score.degradation_reasons = _safe_str_list(data.get("degradation_reasons"))
    return score


def _deserialize_dimension(data: Any) -> DimensionScore:
    if not isinstance(data, dict):
        return DimensionScore()
    return DimensionScore(
        score=float(data.get("score", 0)),
        weight=float(data.get("weight", 0.20)),
        evidence=data.get("evidence") or {},
        suggestions=_safe_str_list(data.get("suggestions")),
    )


def serialize_analysis(analysis: VideoAnalysis) -> Dict[str, Any]:
    """Convert a ``VideoAnalysis`` to a JSON‑compatible dict."""
    return {
        "_format": "qianchuan_analysis_v1",
        "structure_description": analysis.structure_description,
        "segments": analysis.segments,
        "hook_analysis": {
            "hook_type": analysis.hook_analysis.hook_type,
            "effectiveness": analysis.hook_analysis.effectiveness,
            "visual_elements": analysis.hook_analysis.visual_elements,
            "audio_elements": analysis.hook_analysis.audio_elements,
            "text_overlay": analysis.hook_analysis.text_overlay,
        },
        "visual_style": {
            "dominant_colors": analysis.visual_style.dominant_colors,
            "lighting": analysis.visual_style.lighting,
            "shot_types": analysis.visual_style.shot_types,
            "text_overlay_style": analysis.visual_style.text_overlay_style,
            "composition": analysis.visual_style.composition,
        },
        "audio_rhythm": {
            "bpm_estimate": analysis.audio_rhythm.bpm_estimate,
            "energy_level": analysis.audio_rhythm.energy_level,
            "has_background_music": analysis.audio_rhythm.has_background_music,
            "has_sfx": analysis.audio_rhythm.has_sfx,
            "speech_pace": analysis.audio_rhythm.speech_pace,
        },
        "conversion_elements": [
            {"element_type": e.element_type, "description": e.description, "strength": e.strength}
            for e in analysis.conversion_elements
        ],
        "audience_adaptation": {
            "primary_audience": analysis.audience_adaptation.primary_audience,
            "pain_points_addressed": analysis.audience_adaptation.pain_points_addressed,
            "trust_signals": analysis.audience_adaptation.trust_signals,
        },
        "reusable_patterns": [
            {"pattern": p.pattern, "category": p.category, "confidence": p.confidence}
            for p in analysis.reusable_patterns
        ],
        "risks": analysis.risks,
        "improvement_suggestions": analysis.improvement_suggestions,
        "material_errors": analysis.material_errors,
    }


def deserialize_analysis(data: Any) -> Optional[VideoAnalysis]:
    """Parse a stored analysis dict/string back to ``VideoAnalysis``.

    Returns ``None`` on unparseable input.
    """
    if data is None:
        return None
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    if data.get("_format") != "qianchuan_analysis_v1":
        return None

    analysis = VideoAnalysis(
        structure_description=str(data.get("structure_description", "")),
        segments=_safe_segments(data.get("segments")),
        hook_analysis=_dict_to_hook_analysis(data.get("hook_analysis") or {}),
        visual_style=_dict_to_visual_style(data.get("visual_style") or {}),
        audio_rhythm=_dict_to_audio_rhythm(data.get("audio_rhythm") or {}),
        conversion_elements=_dict_to_conversion_elements(data.get("conversion_elements")),
        audience_adaptation=_dict_to_audience_adaptation(data.get("audience_adaptation") or {}),
        reusable_patterns=_dict_to_reusable_patterns(data.get("reusable_patterns")),
        risks=_safe_str_list(data.get("risks")),
        improvement_suggestions=_safe_str_list(data.get("improvement_suggestions")),
        material_errors=_safe_str_list(data.get("material_errors")),
    )
    return analysis


# ---------------------------------------------------------------------------
# DB helper: update feedback fields on a clip_group row
# ---------------------------------------------------------------------------


async def update_db_feedback(
    db_path: str,
    group_id: int,
    score: Optional[QualityScore] = None,
    review: Optional[Dict[str, Any]] = None,
    segments: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Update ``qianchuan_score``, ``qianchuan_review``, ``qianchuan_segments``
    on a clip_group row using ``aiosqlite``.

    This is a convenience helper; callers may also write to the database
    directly.  No schema migration is performed.
    """
    import aiosqlite

    updates: Dict[str, Any] = {}
    if score is not None:
        updates["qianchuan_score"] = json.dumps(serialize_score(score), ensure_ascii=False)
    if review is not None:
        updates["qianchuan_review"] = json.dumps(review, ensure_ascii=False)
    if segments is not None:
        updates["qianchuan_segments"] = json.dumps(segments, ensure_ascii=False)

    if not updates:
        return

    set_clause = ", ".join(f"{col} = ?" for col in updates)
    values = list(updates.values()) + [group_id]

    async with aiosqlite.connect(db_path) as db:
        await db.execute(f"UPDATE clip_groups SET {set_clause} WHERE id = ?", values)
        await db.commit()
