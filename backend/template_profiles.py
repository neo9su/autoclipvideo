"""Static, extensible reference-video profiles for realistic clip selection."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


PROFILE_DIR = Path(__file__).with_name("templates")


@dataclass(frozen=True)
class TemplateProfile:
    """A reviewable description of the structure of a reference video."""

    name: str
    duration_target: tuple[float, float]
    audio_policy: str
    transition_policy: str
    bgm_policy: str
    shot_sequence: tuple[dict[str, Any], ...]
    subtitle_overlay_policy: dict[str, Any]
    disabled_items: tuple[str, ...]


def load_template_profiles(directory: Path = PROFILE_DIR) -> dict[str, TemplateProfile]:
    """Load all JSON profiles from *directory*, ignoring malformed files safely."""
    profiles: dict[str, TemplateProfile] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            profile = TemplateProfile(
                name=str(raw["name"]),
                duration_target=tuple(float(v) for v in raw["duration_target"]),
                audio_policy=str(raw["audio_policy"]),
                transition_policy=str(raw["transition_policy"]),
                bgm_policy=str(raw["bgm_policy"]),
                shot_sequence=tuple(raw["shot_sequence"]),
                subtitle_overlay_policy=dict(raw.get("subtitle_overlay_policy", {})),
                disabled_items=tuple(raw.get("disabled_items", [])),
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        profiles[profile.name] = profile
    return profiles


def get_template_profile(name: str = "英区女高齐刘海") -> TemplateProfile | None:
    """Return a named profile; adding another JSON file requires no selector change."""
    return load_template_profiles().get(name)


def _role_score(segment: Any, role: dict[str, Any]) -> float:
    text = str(getattr(segment, "text", ""))
    category = str(getattr(segment, "category", "neutral"))
    haystack = f"{text} {category}".lower()
    score = 0.0
    for keyword in role.get("keywords", []):
        if str(keyword).lower() in haystack:
            score += 3.0
    for category_name in role.get("categories", []):
        if category == category_name:
            score += 2.0
    # A generic talking-head sentence is not product evidence for realistic clips.
    if role.get("requires_visual_evidence") and category in {"neutral", "scene", "social_proof"}:
        score -= 2.0
    return score


def match_template_roles(
    segments: Iterable[Any], profile: TemplateProfile,
) -> tuple[list[Any], dict[str, Any]]:
    """Assign each selected segment at most one role, without reordering it."""
    candidates = list(segments)
    used: set[int] = set()
    matches: list[dict[str, Any]] = []
    for role in profile.shot_sequence:
        scored = sorted(
            (( _role_score(segment, role), index, segment) for index, segment in enumerate(candidates)
             if index not in used),
            key=lambda item: (item[0], -float(getattr(item[2], "start", 0))),
            reverse=True,
        )
        if not scored or scored[0][0] <= 0:
            continue
        score, index, segment = scored[0]
        used.add(index)
        setattr(segment, "template_role", role["role"])
        matches.append({
            "role": role["role"],
            "segment_idx": getattr(segment, "idx", None),
            "start": getattr(segment, "start", None),
            "end": getattr(segment, "end", None),
            "score": round(score, 2),
            "reason": f"matched {role['role']} from category/text evidence",
        })
    matched_roles = {item["role"] for item in matches}
    missing = [role["role"] for role in profile.shot_sequence if role["role"] not in matched_roles]
    return candidates, {
        "template_name": profile.name,
        "matched_roles": matches,
        "missing_roles": missing,
        "selection_reasons": [
            "original chronological order retained where possible",
            "roles without suitable source evidence were not forced",
            "generic talking-head-only segments were penalized",
        ],
    }

