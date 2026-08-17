import asyncio

from backend.duration_policy import classify_duration


def test_duration_boundary_is_inclusive():
    assert classify_duration(27.9) == ("too_short", "too_short")
    assert classify_duration(27.99) == ("too_short", "too_short")
    assert classify_duration(28.0) == ("eligible", None)
    assert classify_duration(28.01) == ("eligible", None)


def test_invalid_duration_is_unavailable_not_too_short():
    assert classify_duration(None) == ("unavailable", "duration_unavailable")
    assert classify_duration("not-a-duration") == ("unavailable", "duration_unavailable")
    assert classify_duration(0) == ("unavailable", "duration_unavailable")
