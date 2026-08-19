import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from backend.api_v2 import _build_qianchuan_script_segments
from scripts.batch_qianchuan_regen import recording_asset_paths


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


def test_recovery_resolves_windows_source_and_mp4_srt_sidecar(tmp_path: Path) -> None:
    """Read-only recovery must find recorder paths without inventing basenames."""
    source = tmp_path / "素材" / "源视频.mp4"
    source.parent.mkdir()
    source.write_bytes(b"video")
    sidecar = Path(f"{source}.srt")
    sidecar.write_text("1\n00:00:00,000 --> 00:00:01,000\n字幕\n", encoding="utf-8")

    resolved_source, sidecars = recording_asset_paths(tmp_path, r"素材\源视频.mp4")

    assert resolved_source == source
    assert sidecar in sidecars
    assert any(candidate.is_file() and candidate.stat().st_size > 0 for candidate in sidecars)


def test_recovery_rejects_absolute_or_parent_paths(tmp_path: Path) -> None:
    """A malformed DB filename must remain unavailable rather than escape root."""
    absolute_source, absolute_sidecars = recording_asset_paths(tmp_path, "/tmp/source.mp4")
    parent_source, parent_sidecars = recording_asset_paths(tmp_path, "../source.mp4")

    assert not absolute_source and not absolute_sidecars
    assert not parent_source and not parent_sidecars


def test_recovery_resolves_windows_source_and_mp4_srt_sidecar(tmp_path: Path) -> None:
    """Read-only recovery must find recorder paths without inventing basenames."""
    source = tmp_path / "素材" / "源视频.mp4"
    source.parent.mkdir()
    source.write_bytes(b"video")
    sidecar = Path(f"{source}.srt")
    sidecar.write_text("1\n00:00:00,000 --> 00:00:01,000\n字幕\n", encoding="utf-8")

    resolved_source, sidecars = recording_asset_paths(tmp_path, r"素材\源视频.mp4")

    assert resolved_source == source
    assert sidecar in sidecars
    assert any(candidate.is_file() and candidate.stat().st_size > 0 for candidate in sidecars)


def test_recovery_rejects_absolute_or_parent_paths(tmp_path: Path) -> None:
    """A malformed DB filename must remain unavailable rather than escape root."""
    absolute_source, absolute_sidecars = recording_asset_paths(tmp_path, "/tmp/source.mp4")
    parent_source, parent_sidecars = recording_asset_paths(tmp_path, "../source.mp4")

    assert not absolute_source and not absolute_sidecars
    assert not parent_source and not parent_sidecars
