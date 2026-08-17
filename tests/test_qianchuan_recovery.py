import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from backend.api_v2 import _build_qianchuan_script_segments


@pytest.mark.parametrize("scene_type", ["result_hook", "product_proof", "cta"])
def test_qianchuan_background_segments_keep_scene_type(scene_type: str) -> None:
    """Background generation must pass each scene type into the matcher/composer."""
    script = {
        "scenes": [
            {
                "scene_id": 4,
                "scene_type": scene_type,
                "voiceover_text": "展示发型效果",
                "visual_requirements": ["自然"],
                "duration": 3.0,
            }
        ]
    }

    segments = _build_qianchuan_script_segments(
        script, [{"scene_id": 4, "duration": 4.25}]
    )

    assert segments == [
        {
            "text": "展示发型效果",
            "voiceover_text": "展示发型效果",
            "visual_keywords": ["自然"],
            "priority_shots": [],
            "duration": 4.25,
            "scene_type": scene_type,
            "scene_id": 4,
        }
    ]
