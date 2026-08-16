"""Regression tests for complete realistic/conservative subtitle rendering."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

from editor import Seg, build_ass, parse_srt, resolve_subtitle_font_path


def test_parse_srt_preserves_multiline_and_bom(tmp_path):
    source = tmp_path / "source.srt"
    source.write_text(
        "\ufeff2\r\n00:00:01,000 --> 00:00:03,000\r\n第一行\r\n第二行\r\n\r\n"
        "1\n00:00:00,000 --> 00:00:01,000\n开场\n",
        encoding="utf-8",
    )

    segments = parse_srt(str(source))

    assert [segment.idx for segment in segments] == [1, 2]
    assert segments[1].text == "第一行 第二行"


def test_parse_srt_accepts_optional_timestamp_settings(tmp_path):
    source = tmp_path / "settings.srt"
    source.write_text(
        "1\n00:00:00,000 --> 00:00:02,000 align:start position:10%\n完整字幕\n",
        encoding="utf-8",
    )

    segments = parse_srt(str(source))

    assert len(segments) == 1
    assert segments[0].start == 0
    assert segments[0].end == 2
    assert segments[0].text == "完整字幕"


def test_realistic_ass_keeps_all_text_and_uses_requested_style(tmp_path):
    selected = [Seg(idx=1, start=10, end=14, text="完整内容", transition="cut:0")]
    source = [Seg(idx=1, start=10, end=14, text="自然 蓬松 完整内容")]

    ass = build_ass(selected, source, realistic=True)

    assert "WenYue XinQingNianTi" in ass
    assert "完整内容" in ass
    assert "自然" in ass
    assert "&H00FFFFFF" in ass
    assert "\\3c&H00000000&\\bord1" in ass
    assert "&H000000FF" in ass


def test_ass_renders_each_selected_cue_once_without_truncation():
    selected = [
        Seg(idx=1, start=0, end=2, text="第一句"),
        Seg(idx=2, start=2, end=4, text="第二句"),
    ]

    ass = build_ass(selected, selected, realistic=False)

    assert ass.count("第一句") == 1
    assert ass.count("第二句") == 1
    assert "第一句" in ass and "第二句" in ass


def test_subtitle_font_path_is_bundled():
    assert Path(resolve_subtitle_font_path()).name == "WenYue-XinQingNianTi-W8-J-2.otf"
