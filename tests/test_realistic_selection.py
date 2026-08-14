"""Selection tests for the conservative realistic clip preset."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

from editor import Seg, _select_realistic_window


def test_realistic_selector_prefers_one_chronological_window():
    segments = [
        Seg(idx=i, start=i * 12.0, end=i * 12.0 + 8.0, text=f"detail {i}", score=10 - i)
        for i in range(8)
    ]
    selected, explanation = _select_realistic_window(segments)

    assert 4 <= len(selected) <= 8
    assert selected == sorted(selected, key=lambda segment: segment.start)
    assert sum(segment.duration for segment in selected) >= 45.0
    assert explanation["clip_style"] == "realistic"
    assert explanation["selected_window"]["start_sec"] == selected[0].start
    assert explanation["selected_window"]["end_sec"] == selected[-1].end


def test_realistic_selector_honors_detected_source_window():
    segments = [
        Seg(idx=i, start=float(i * 10), end=float(i * 10 + 9), text="product", score=1)
        for i in range(10)
    ]
    selected, explanation = _select_realistic_window(
        segments, source_window={"start_sec": 30, "end_sec": 89}
    )

    assert selected
    assert selected[0].start >= 30
    assert selected[-1].end <= 89
    assert explanation["source_window"]["start_sec"] == 30
