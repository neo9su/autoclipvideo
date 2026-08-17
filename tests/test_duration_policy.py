import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from duration_policy import classify_duration, is_processable_duration


def test_duration_boundaries():
    assert classify_duration(27.9) == "too_short"
    assert classify_duration(27.99) == "too_short"
    assert classify_duration(28.0) == "accepted"
    assert classify_duration(28.01) == "accepted"


def test_invalid_duration_is_unavailable_and_not_processable():
    for value in (None, "", "bad", 0, -1, float("nan")):
        assert classify_duration(value) == "duration_unavailable"
        assert not is_processable_duration(value)
