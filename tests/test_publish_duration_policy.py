from backend.publish_policy import (
    MAX_PUBLISH_DURATION_SECONDS,
    MIN_PUBLISH_DURATION_SECONDS,
    validate_publish_duration,
)


def test_publish_policy_accepts_videos_above_old_limit():
    assert MAX_PUBLISH_DURATION_SECONDS == 300.0
    assert validate_publish_duration(150.1) is None
    assert validate_publish_duration(162.8) is None
    assert validate_publish_duration(300.0) is None


def test_publish_policy_rejects_only_outside_new_duration_bounds():
    too_short = validate_publish_duration(MIN_PUBLISH_DURATION_SECONDS - 0.1)
    too_long = validate_publish_duration(MAX_PUBLISH_DURATION_SECONDS + 0.1)

    assert too_short and "≥ 15 秒" in too_short
    assert too_long and "≤ 300 秒" in too_long
