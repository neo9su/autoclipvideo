import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

from editor import Seg
from template_profiles import get_template_profile, match_template_roles


def test_reference_profile_contains_realistic_structure():
    profile = get_template_profile()
    assert profile is not None
    assert profile.audio_policy == "preserve_original"
    assert profile.transition_policy == "mostly_hard_cut"
    assert {role["role"] for role in profile.shot_sequence} >= {
        "hook_proof", "realism_detail", "styling_demo", "trust_detail"
    }


def test_role_matching_keeps_source_order_and_reports_missing_roles():
    profile = get_template_profile()
    segments = [
        Seg(1, 10, 14, "风吹也不掉", category="comfort"),
        Seg(2, 20, 24, "看发缝和发根", category="detail"),
        Seg(3, 30, 35, "梳一下戴上去", category="wearing"),
    ]
    _, explanation = match_template_roles(segments, profile)
    assert [segment.start for segment in segments] == [10, 20, 30]
    assert {item["role"] for item in explanation["matched_roles"]} >= {
        "hook_proof", "realism_detail", "styling_demo"
    }
    assert "beauty_reveal" in explanation["missing_roles"]

