import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

from publish_policy import (  # noqa: E402
    MAX_PUBLISH_DURATION_SECONDS,
    validate_publish_duration,
)


def test_publish_maximum_is_300_seconds():
    assert MAX_PUBLISH_DURATION_SECONDS == 300.0


def test_publish_accepts_video_above_previous_limit():
    assert validate_publish_duration(150.1) is None
    assert validate_publish_duration(162.8) is None
    assert validate_publish_duration(300.0) is None


def test_publish_rejects_video_above_new_limit():
    reason = validate_publish_duration(300.1)
    assert reason == "时长超限（300.1s，需要 ≤ 300 秒）"


def test_publish_rejects_non_finite_duration():
    assert validate_publish_duration(float("nan")) == "视频时长不可用（媒体探测失败或缺失）"
    assert validate_publish_duration(float("inf")) == "视频时长不可用（媒体探测失败或缺失）"
