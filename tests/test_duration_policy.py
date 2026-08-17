import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from duration_policy import classify_duration, duration_reason, is_processable_duration


def test_boundary_is_inclusive():
    assert classify_duration(27.9) == "too_short"
    assert classify_duration(27.99) == "too_short"
    assert classify_duration(28.0) == "accepted"
    assert classify_duration(28.01) == "accepted"


def test_invalid_and_missing_duration_are_unavailable():
    for value in (None, "", "not-a-number", float("nan"), float("inf"), -1):
        assert classify_duration(value) == "unavailable"
        assert not is_processable_duration(value)


def test_reasons_are_machine_and_ui_readable():
    assert duration_reason(23) == "too_short"
    assert duration_reason(None) == "duration_unavailable"
    assert duration_reason(28) is None
