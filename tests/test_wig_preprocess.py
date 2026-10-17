from backend.wig_preprocess import (
    build_asset_name,
    extract_features,
    filter_entries_to_windows,
    group_same_wig_segments,
    qianchuan_output_spec,
    resolve_spoken_product,
    retention_hook_plan,
    select_identity_windows,
)


PRODUCTS = [
    {"id": 1, "product_name": "夺回&人生"},
    {"id": 2, "product_name": "氧气少女"},
]


def test_compound_product_name_matches_either_spoken_component():
    assert resolve_spoken_product("这是夺回，今天看这个颜色", PRODUCTS)["product_key"] == "1"
    assert resolve_spoken_product("人生这一款不用戴发网", PRODUCTS)["product_key"] == "1"


def test_colliding_alias_does_not_guess_product():
    products = PRODUCTS + [{"id": 3, "product_name": "赢家", "aliases": ["人生"]}]
    result = resolve_spoken_product("人生这一款", products)
    assert not result["ok"]
    assert result["reason"] == "ambiguous_product_mention"


def test_name_contains_product_color_and_observed_features():
    features = extract_features("齐刘海长卷发，免发网，仿递针工艺")
    assert build_asset_name("夺回&人生", "自然黑", features) == "夺回&人生_自然黑_齐刘海_长发_卷发_免发网_仿递针"


def test_unknown_identity_segments_are_never_merged():
    grouped = group_same_wig_segments([
        {"recording_id": 7, "start_sec": 1, "identity_key": "product:1"},
        {"recording_id": 7, "start_sec": 9, "identity_key": "product:1"},
        {"recording_id": 7, "start_sec": 20},
        {"recording_id": 7, "start_sec": 30},
    ])
    assert len(grouped["product:1"]) == 2
    assert len(grouped) == 3


def test_retention_hooks_cover_3_5_10_15_30_seconds_when_duration_allows():
    assert [item["time"] for item in retention_hook_plan(45)] == [0, 3, 5, 10, 15, 30]
    assert [item["time"] for item in retention_hook_plan(12)] == [0, 3, 5, 10]


def test_vertical_2k_spec_is_inside_qianchuan_limits():
    spec = qianchuan_output_spec()
    assert spec["aspect_ratio"] == "9:16"
    assert spec["resolution"] == "1440x2560"
    assert spec["min_video_bitrate_kbps"] == 516
    assert spec["duration_range_seconds"] == [4, 300]


def test_same_wig_rewear_windows_are_kept_and_other_wig_is_excluded():
    boundaries = [
        {"wig": "夺回", "color": "自然黑", "start_sec": 10, "end_sec": 50},
        {"wig": "氧气少女", "color": "棕色", "start_sec": 50, "end_sec": 90},
        {"wig": "人生", "color": "自然黑", "start_sec": 100, "end_sec": 140},
    ]
    selected = select_identity_windows(boundaries, "夺回&人生", "自然黑")
    assert [(item["start_sec"], item["end_sec"]) for item in selected] == [(10, 50), (100, 140)]
    entries = [
        {"start": 12, "end": 15, "text": "夺回"},
        {"start": 55, "end": 58, "text": "另一款"},
        {"start": 105, "end": 108, "text": "人生"},
    ]
    assert [item["text"] for item in filter_entries_to_windows(entries, selected)] == ["夺回", "人生"]


def test_ambiguous_multi_style_target_has_no_render_windows():
    boundaries = [{"wig": "直发", "start_sec": 0, "end_sec": 20}]
    assert select_identity_windows(boundaries, "直发/卷发", "黑色/橘色") == []
