from backend.wig_visual_identity import accepted_visual_windows, sample_times


def test_sampling_avoids_transition_edges():
    assert sample_times({"start_sec": 10, "end_sec": 20}) == [11, 13, 15, 17, 19]


def test_same_wig_rewear_is_kept_but_changed_style_is_rejected():
    windows = [{"start_sec": 0, "end_sec": 20}, {"start_sec": 40, "end_sec": 60}, {"start_sec": 80, "end_sec": 100}]
    observations = []
    for index, signature in enumerate(("棕|长|卷|无刘海|仿递针", "棕|长|卷|无刘海|仿递针", "黑|短|直|齐刘海|普通")):
        observations.extend({"window_index": index, "wear_state": "stable_wearing", "style_signature": signature} for _ in range(5))
    result = accepted_visual_windows(windows, observations)
    assert [(item["start_sec"], item["end_sec"]) for item in result] == [(0, 20), (40, 60)]


def test_takeoff_or_uncertain_window_is_rejected():
    windows = [{"start_sec": 0, "end_sec": 20}]
    observations = [
        {"window_index": 0, "wear_state": state, "style_signature": "棕|长|卷|无刘海|仿递针"}
        for state in ("stable_wearing", "transition", "no_wig", "stable_wearing", "stable_wearing")
    ]
    assert accepted_visual_windows(windows, observations) == []
