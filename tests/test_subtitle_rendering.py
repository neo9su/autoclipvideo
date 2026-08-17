"""Regression tests for complete realistic/conservative subtitle rendering."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

from editor import Seg, build_ass, build_conservative_sound_cues, parse_srt, resolve_subtitle_font_path


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


def test_parse_srt_accepts_cues_without_numeric_sequence(tmp_path):
    source = tmp_path / "sequence-less.srt"
    source.write_text(
        "00:00:00,000 --> 00:00:01,000\n第一条\n\n"
        "garbage\n00:00:01,200 --> 00:00:02,500\n第二条\n",
        encoding="utf-8",
    )

    segments = parse_srt(str(source))

    assert [(segment.start, segment.end, segment.text) for segment in segments] == [
        (0.0, 1.0, "第一条"),
        (1.2, 2.5, "第二条"),
    ]


def test_realistic_and_conservative_ass_keep_all_text_and_use_requested_style():
    selected = [Seg(idx=1, start=10, end=14, text="完整内容", transition="cut:0")]
    source = [Seg(idx=1, start=10, end=14, text="自然 蓬松 完整内容")]

    for realistic in (True, False):
        ass = build_ass(selected, source, realistic=realistic)

        assert "WenYue XinQingNianTi" in ass
        assert "完整内容" in ass
        assert "自然" in ass
        assert "&H00FFFFFF" in ass
        assert "\\3c&H00000000&\\bord1" in ass
        assert "&H000000FF" in ass


def test_ass_uses_every_original_cue_when_scene_text_was_merged():
    selected = [Seg(idx=1, start=10, end=16, text="合并后的评分文本", transition="cut:0")]
    source = [
        Seg(idx=1, start=10, end=12, text="第一句"),
        Seg(idx=2, start=12, end=14, text="第二句"),
        Seg(idx=3, start=14, end=16, text="第三句"),
    ]

    ass = build_ass(selected, source, realistic=True)

    assert all(text in ass for text in ("第一句", "第二句", "第三句"))


def test_realistic_ass_renders_every_original_cue_in_selected_window():
    selected = [Seg(idx=10, start=10, end=16, text="scene", transition="cut:0")]
    source = [
        Seg(idx=1, start=10.0, end=11.2, text="第一句"),
        Seg(idx=2, start=11.2, end=13.0, text="第二句显白"),
        Seg(idx=3, start=13.0, end=15.8, text="第三句完整保留"),
    ]

    ass = build_ass(selected, source, realistic=True)

    dialogue = [line for line in ass.splitlines() if line.startswith("Dialogue:")]
    assert len(dialogue) == len(source)
    assert all(text in ass for text in ("第一句", "第二句", "第三句完整保留"))
    assert "0:00:10" not in ass  # cues are rebased to the clip timeline
    assert "0:00:00.00" in ass


def test_subtitle_font_path_is_bundled():
    assert Path(resolve_subtitle_font_path()).name == "WenYue-XinQingNianTi-W8-J-2.otf"


def test_ass_uses_original_cue_timing_when_selection_segments_are_merged():
    selected = [
        Seg(idx=1, start=10, end=16, text="第一句 第二句", transition="cut:0"),
    ]
    source_cues = [
        Seg(idx=1, start=10, end=12, text="第一句"),
        Seg(idx=2, start=12.2, end=14, text="自然 第二句"),
        Seg(idx=3, start=14.2, end=16, text="最后一句"),
    ]

    ass = build_ass(selected, source_cues, realistic=True)

    assert ass.count("Dialogue:") == 3
    assert "0:00:00.00,0:00:02.00" in ass
    assert "0:00:02.20,0:00:04.00" in ass
    assert "0:00:04.20,0:00:06.00" in ass
    assert "{\\c&H000000FF&}自然{\\r}" in ass


def test_ass_wrap_does_not_drop_text_or_split_ass_line_break_escape():
    source_text = "这是一个超过十四个汉字的完整字幕内容，用于验证不会截断。"
    selected = [Seg(idx=1, start=0, end=3, text=source_text, transition="cut:0")]

    ass = build_ass(selected, selected, realistic=True)

    rendered_text = ass.split("Dialogue:", 1)[1].split("\n", 1)[0]
    rendered_text = rendered_text.replace(r"\N", "")
    assert source_text in rendered_text
    assert r"\N" in ass
    assert "\\" + "N" not in ass.replace(r"\N", "")


def test_ass_escapes_source_override_characters_without_dropping_text():
    selected = [Seg(idx=1, start=0, end=3, text="scene", transition="cut:0")]
    source_cues = [Seg(idx=1, start=0, end=3, text="保留\\路径 {原文}")]

    ass = build_ass(selected, source_cues, realistic=True)

    assert "保留\\\\路径 \\{原文\\}" in ass


def test_conservative_subtitles_are_at_most_two_lines_and_style_keywords():
    selected = [Seg(idx=1, start=0, end=4, text="scene", transition="cut:0")]
    source = [Seg(idx=1, start=0, end=4, text="这是一个非常长的字幕内容显白自然蓬松")]

    ass = build_ass(selected, source, conservative=True)
    dialogue = next(line for line in ass.splitlines() if line.startswith("Dialogue:"))
    assert dialogue.count(r"\N") <= 1
    assert r"{\c&H0000CCFF&\3c&H00FFFFFF&\bord3}显白" in dialogue
    assert r"{\c&H0000CCFF&\3c&H00FFFFFF&\bord3}自然" in dialogue


def test_conservative_keyword_sound_cues_are_timed_and_idempotent():
    selected = [Seg(idx=5, start=10, end=14, text="scene", transition="cut:0")]
    source = [Seg(idx=5, start=10, end=12, text="显白自然")]

    cues = build_conservative_sound_cues(selected, source)
    assert [cue["keyword"] for cue in cues] == ["显白", "自然"]
    assert [cue["time"] for cue in cues] == [0.05, 0.05]
    assert len({cue["idempotency_key"] for cue in cues}) == len(cues)
    assert all(cue["reason"] == "conservative_keyword" for cue in cues)
