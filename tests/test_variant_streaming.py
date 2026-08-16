from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

from main import _content_disposition_for_path, _variant_retry_assignments


def test_content_disposition_is_ascii_safe_and_preserves_utf8_name():
    header = _content_disposition_for_path("/recordings/剪辑\r\n版.mp4")

    assert header.startswith('inline; filename="video.mp4"; filename*=UTF-8\'\'')
    assert "剪辑" not in header
    assert "%E5%89%AA" in header
    assert "\r" not in header and "\n" not in header


def test_variant_retry_assignments_mark_requested_variants_running():
    assert _variant_retry_assignments(["conservative"]) == [
        "conservative_status = 1",
        "conservative_error = NULL",
        "conservative_final_video = NULL",
    ]
    assert _variant_retry_assignments(["realistic", "conservative"])[0] == "realistic_status = 1"
