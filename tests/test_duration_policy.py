from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

from duration_policy import classify_duration


def test_duration_boundaries_are_deterministic():
    assert classify_duration(27.9).status == "too_short"
    assert classify_duration(27.99).eligible is False
    assert classify_duration(28.0).eligible is True
    assert classify_duration(42.5).eligible is True


def test_missing_or_invalid_duration_is_unavailable_and_not_short():
    assert classify_duration(None).status == "unavailable"
    assert classify_duration("not-a-duration").reason == "duration_unavailable"
