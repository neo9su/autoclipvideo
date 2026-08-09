"""Tests for qianchuan_learning.py.

Covers: scoring boundaries, bad JSON, missing materials, schema field
compatibility, feedback aggregation, serialization round-trips.
No remote GPU or real LLM — all external deps are mocked/stubbed.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

# Module under test
import qianchuan_learning as qlearn  # noqa: E402
from qianchuan_policy import build_qianchuan_metadata, validate_qianchuan_metadata  # noqa: E402


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_llm_response(structure_desc: str = "A structured product ad video") -> str:
    """Return a well-formed LLM JSON response."""
    return json.dumps({
        "structure_description": structure_desc,
        "segments": [
            {
                "start_s": 0.0,
                "end_s": 3.0,
                "type": "result_hook",
                "description": "Shows final result immediately",
                "key_frames": "frame at 1.5s",
            },
            {
                "start_s": 3.0,
                "end_s": 7.0,
                "type": "pain_point",
                "description": "Highlights wig discomfort",
                "key_frames": "frame at 5s",
            },
            {
                "start_s": 7.0,
                "end_s": 13.0,
                "type": "product_proof",
                "description": "Close-up of hair parting",
                "key_frames": "frame at 10s",
            },
            {
                "start_s": 13.0,
                "end_s": 19.0,
                "type": "tryon_result",
                "description": "Wearer showcases result",
                "key_frames": "frame at 16s",
            },
            {
                "start_s": 19.0,
                "end_s": 23.0,
                "type": "cta",
                "description": "Call to action with cart link",
                "key_frames": "frame at 21s",
            },
        ],
        "hook_analysis": {
            "hook_type": "result",
            "effectiveness": "high",
            "visual_elements": ["close_up_face", "bright_colors"],
            "audio_elements": ["upbeat_bgm"],
            "text_overlay": True,
        },
        "visual_style": {
            "dominant_colors": ["#FF6B6B", "#4ECDC4"],
            "lighting": "studio",
            "shot_types": ["closeup", "mid", "closeup"],
            "text_overlay_style": "bold",
            "composition": "centered",
        },
        "audio_rhythm": {
            "bpm_estimate": 120,
            "energy_level": "high",
            "has_background_music": True,
            "has_sfx": True,
            "speech_pace": "moderate",
        },
        "conversion_elements": [
            {"element_type": "cta", "description": "Yellow cart button", "strength": "strong"},
            {"element_type": "trust_proof", "description": "Real user before/after", "strength": "strong"},
            {"element_type": "social_proof", "description": "Thousands sold badge", "strength": "moderate"},
        ],
        "audience_adaptation": {
            "primary_audience": "产后妈妈群",
            "pain_points_addressed": ["脱发困扰", "发网不适"],
            "trust_signals": ["真实佩戴", "免发网"],
        },
        "reusable_patterns": [
            {"pattern": "result-first hook shows transformation in 2s", "category": "hook", "confidence": 0.9},
            {"pattern": "keyword pop + push-in on CTA", "category": "cta", "confidence": 0.85},
        ],
        "risks": ["Audio level slightly high on CTA segment"],
        "improvement_suggestions": ["Normalise audio across segments", "Add social proof badge earlier"],
    })


def _create_analysis_dir(base: Path, with_hero: bool = True, with_spectrogram: bool = True, with_1fps: bool = True) -> Path:
    """Create a mock analysis directory with material files."""
    d = base / "analysis_vid_001"
    d.mkdir(parents=True, exist_ok=True)

    if with_hero:
        (d / "hero.jpg").touch()
    if with_spectrogram:
        (d / "spectrogram.jpg").touch()
    if with_1fps:
        fps_dir = d / "1fps"
        fps_dir.mkdir(exist_ok=True)
        for i in range(10):
            (fps_dir / f"frame_{i:04d}.jpg").touch()
    # timepoint frames
    for ts in ("0.5", "1.5", "3.0", "7.0"):
        (d / f"{ts}.jpg").touch()

    return d


# ── Tests: material scanning ─────────────────────────────────────────────────


def test_scan_materials_fully_populated():
    with tempfile.TemporaryDirectory() as tmp:
        d = _create_analysis_dir(Path(tmp))
        materials, errors = qlearn._scan_materials(str(d))
        assert not errors
        assert materials["hero_path"]
        assert materials["spectrogram_path"]
        assert materials["1fps_count"] == 10
        assert materials["timepoint_count"] == 4


def test_scan_materials_missing_directory():
    materials, errors = qlearn._scan_materials("/nonexistent/directory/xyz123")
    assert errors
    assert "does not exist" in errors[0]
    assert materials == {}


def test_scan_materials_partial_missing():
    with tempfile.TemporaryDirectory() as tmp:
        d = _create_analysis_dir(Path(tmp), with_hero=False, with_spectrogram=False, with_1fps=True)
        materials, errors = qlearn._scan_materials(str(d))
        # hero.jpg and spectrogram.jpg are not required, so no errors
        assert not errors
        assert materials["hero_path"] is None
        assert materials["spectrogram_path"] is None
        assert materials["1fps_count"] == 10


# ── Tests: JSON parsing ─────────────────────────────────────────────────────


def test_parse_valid_json():
    parsed, err = qlearn._parse_analysis_json('{"key": "value"}')
    assert err is None
    assert parsed == {"key": "value"}


def test_parse_code_fence_json():
    raw = '```json\n{"code": "fenced"}\n```'
    parsed, err = qlearn._parse_analysis_json(raw)
    assert err is None
    assert parsed == {"code": "fenced"}


def test_parse_bare_code_fence_json():
    raw = '```\n{"bare": "fenced"}\n```'
    parsed, err = qlearn._parse_analysis_json(raw)
    assert err is None
    assert parsed == {"bare": "fenced"}


def test_parse_extract_json_substring():
    raw = 'Some preamble text {"extracted": true} and trailing text'
    parsed, err = qlearn._parse_analysis_json(raw)
    assert err is None
    assert parsed == {"extracted": True}


def test_parse_empty_prompt():
    parsed, err = qlearn._parse_analysis_json("")
    assert err is not None
    assert parsed == {}


def test_parse_utterly_bad_text():
    parsed, err = qlearn._parse_analysis_json("This is not JSON at all. Just plain text.")
    assert err is not None
    assert parsed == {}


def test_parse_none_like():
    parsed, err = qlearn._parse_analysis_json("   ")
    assert err is not None
    assert parsed == {}


# ── Tests: analyze_video ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_analyze_video_empty_directory():
    with tempfile.TemporaryDirectory() as tmp:
        empty_dir = Path(tmp) / "empty"
        empty_dir.mkdir()
        result = await qlearn.analyze_video(str(empty_dir))
        assert isinstance(result, qlearn.VideoAnalysis)
        assert "No usable visual materials" in result.risks[0] or result.material_errors


@pytest.mark.asyncio
async def test_analyze_video_with_llm_success():
    with tempfile.TemporaryDirectory() as tmp:
        d = _create_analysis_dir(Path(tmp))

        async def fake_llm_post(messages, **kwargs):
            return _make_llm_response()

        with patch("qianchuan_learning.llm_post", side_effect=fake_llm_post):
            result = await qlearn.analyze_video(str(d))

    assert result.structure_description == "A structured product ad video"
    assert result.llm_error is None
    assert len(result.segments) == 5
    assert result.hook_analysis.hook_type == "result"
    assert result.hook_analysis.effectiveness == "high"
    assert len(result.conversion_elements) == 3
    assert result.audience_adaptation.primary_audience == "产后妈妈群"
    assert len(result.reusable_patterns) == 2
    assert result.material_errors == []


@pytest.mark.asyncio
async def test_analyze_video_llm_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        d = _create_analysis_dir(Path(tmp))

        async def fake_llm_post(messages, **kwargs):
            return None

        with patch("qianchuan_learning.llm_post", side_effect=fake_llm_post):
            result = await qlearn.analyze_video(str(d))

    assert result.llm_error is not None
    assert "LLM call failed" in result.llm_error
    assert "LLM analysis unavailable" in result.risks[0]


@pytest.mark.asyncio
async def test_analyze_video_llm_returns_bad_json():
    with tempfile.TemporaryDirectory() as tmp:
        d = _create_analysis_dir(Path(tmp))

        async def fake_llm_post(messages, **kwargs):
            return "I cannot analyse this video because reasons."

        with patch("qianchuan_learning.llm_post", side_effect=fake_llm_post):
            result = await qlearn.analyze_video(str(d))

    assert result.llm_error is not None
    assert result.llm_raw == "I cannot analyse this video because reasons."


@pytest.mark.asyncio
async def test_analyze_video_llm_partial_json():
    """LLM returns something that contains partial JSON but the parser extracts what it can."""
    with tempfile.TemporaryDirectory() as tmp:
        d = _create_analysis_dir(Path(tmp))

        async def fake_llm_post(messages, **kwargs):
            return json.dumps({
                "structure_description": "Partial only",
                "segments": [],
                "hook_analysis": {"hook_type": "question"},
            })

        with patch("qianchuan_learning.llm_post", side_effect=fake_llm_post):
            result = await qlearn.analyze_video(str(d))

    assert result.structure_description == "Partial only"
    assert result.hook_analysis.hook_type == "question"
    assert len(result.segments) == 0


@pytest.mark.asyncio
async def test_analyze_video_missing_directory():
    result = await qlearn.analyze_video("/tmp/nonexistent_dir_xyz_12345")
    assert isinstance(result, qlearn.VideoAnalysis)
    assert result.material_errors
    assert "No usable visual materials" in result.risks[0]


# ── Tests: quality scoring ──────────────────────────────────────────────────


def _make_good_analysis() -> qlearn.VideoAnalysis:
    """Return a well-populated analysis fixture."""
    return qlearn.VideoAnalysis(
        structure_description="Well-structured 5-scene ad",
        segments=[
            {"type": "result_hook"}, {"type": "pain_point"},
            {"type": "product_proof"}, {"type": "tryon_result"}, {"type": "cta"},
        ],
        hook_analysis=qlearn.HookAnalysis(hook_type="result", effectiveness="high"),
        visual_style=qlearn.VisualStyle(lighting="studio", shot_types=["closeup", "mid"], composition="centered"),
        audio_rhythm=qlearn.AudioRhythm(energy_level="high", speech_pace="moderate", has_sfx=True),
        conversion_elements=[
            qlearn.ConversionElement(element_type="cta", strength="strong"),
            qlearn.ConversionElement(element_type="trust_proof", strength="strong"),
        ],
        audience_adaptation=qlearn.AudienceAdaptation(primary_audience="产后妈妈群", pain_points_addressed=["脱发"]),
    )


def test_qianchuan_policy_does_not_invent_missing_evidence():
    """An omitted campaign field must remain a delivery blocker."""
    metadata = build_qianchuan_metadata()
    report = validate_qianchuan_metadata(metadata)
    assert not report["eligible_for_delivery"]
    assert "缺少或无效的剪辑模板" in report["errors"]
    assert "缺少 A/B/C 三版本文案" in report["errors"]
    assert "缺少真实感检查" in report["errors"]


def test_qianchuan_policy_accepts_explicit_evidence():
    metadata = build_qianchuan_metadata(
        target_audience="产后妈妈群",
        excluded_audiences=["职场白领群"],
        bid_coefficient=1.0,
        template_type="头皮/发际线微距",
        dedup_actions=["光源", "画幅", "BGM"],
        authenticity_check={"passed": True},
        copy_versions={"A": "文案 A", "B": "文案 B", "C": "文案 C"},
        trust_proof="品牌授权正品保证",
        stability_evidence=["摇头晃脑"],
    )
    assert validate_qianchuan_metadata(metadata)["eligible_for_delivery"]


def test_score_quality_degraded_no_quality_result():
    analysis = _make_good_analysis()
    score = qlearn.score_quality(analysis, quality_result=None)
    assert not score.validated
    assert "no quality_result provided" in score.validation_details[0]
    # With a good analysis the overall should be > 50
    assert score.overall > 50.0
    assert 0.0 <= score.overall <= 100.0


def test_score_quality_with_passing_validation():
    analysis = _make_good_analysis()
    quality_result = {"ok": True, "hard_gate_failures": []}
    score = qlearn.score_quality(analysis, quality_result=quality_result)
    assert score.validated
    assert score.overall > 50.0


def test_score_quality_with_failing_validation():
    analysis = _make_good_analysis()
    quality_result = {"ok": False, "hard_gate_failures": ["score 65.0 below 80"]}
    score = qlearn.score_quality(analysis, quality_result=quality_result)
    assert not score.validated
    assert len(score.validation_details) > 0
    assert len(score.degradation_reasons) > 0


def test_score_quality_none_analysis():
    score = qlearn.score_quality(None)
    assert not score.validated
    # With no analysis, scores should be base defaults
    assert score.visual.score <= 50.0


def test_score_quality_overall_in_range():
    """Score must always be 0-100 regardless of inputs."""
    # Minimal analysis
    score = qlearn.score_quality(qlearn.VideoAnalysis())
    assert 0.0 <= score.overall <= 100.0

    # Edge case: all dimension scores available
    analysis = _make_good_analysis()
    score = qlearn.score_quality(analysis, quality_result={"ok": True, "hard_gate_failures": []})
    assert 0.0 <= score.overall <= 100.0


def test_score_quality_weights_summary():
    """Weights should sum to 1.0."""
    analysis = _make_good_analysis()
    score = qlearn.score_quality(analysis)
    total_weight = (
        score.visual.weight
        + score.audio.weight
        + score.semantic.weight
        + score.structural.weight
        + score.conversion.weight
    )
    assert abs(total_weight - 1.0) < 0.001, f"weights sum to {total_weight}"


def test_score_quality_custom_weights():
    custom = {"visual": 0.40, "audio": 0.15, "semantic": 0.15, "structural": 0.15, "conversion": 0.15}
    analysis = _make_good_analysis()
    score = qlearn.score_quality(analysis, weights=custom)
    assert score.visual.weight == 0.40
    assert score.audio.weight == 0.15


def test_score_quality_dimension_evidence():
    analysis = _make_good_analysis()
    score = qlearn.score_quality(analysis)
    # Each dimension should have evidence dict populated
    assert isinstance(score.visual.evidence, dict)
    assert isinstance(score.audio.evidence, dict)
    assert isinstance(score.semantic.evidence, dict)
    assert isinstance(score.structural.evidence, dict)
    assert isinstance(score.conversion.evidence, dict)


# ── Tests: serialization ────────────────────────────────────────────────────


def test_serialize_score_round_trip():
    analysis = _make_good_analysis()
    original = qlearn.score_quality(analysis)
    serialized = qlearn.serialize_score(original)
    assert serialized["_format"] == "qianchuan_score_v1"
    assert isinstance(serialized["overall"], float)
    assert "dimensions" in serialized

    restored = qlearn.deserialize_score(serialized)
    assert restored is not None
    assert restored.overall == original.overall
    assert restored.visual.score == original.visual.score
    assert restored.validated == original.validated


def test_deserialize_legacy_float_score():
    """Backward-compat: accept a raw float from the DB."""
    score = qlearn.deserialize_score(78.5)
    assert score is not None
    assert score.overall == 78.5


def test_deserialize_legacy_int_score():
    score = qlearn.deserialize_score(80)
    assert score is not None
    assert score.overall == 80.0


def test_deserialize_legacy_json_string_score():
    score = qlearn.deserialize_score('{"overall": 72.3}')
    assert score is not None
    assert score.overall == 72.3


def test_deserialize_none():
    assert qlearn.deserialize_score(None) is None


def test_deserialize_bad_string():
    assert qlearn.deserialize_score("not-json-at-all") is None


def test_deserialize_bad_type():
    assert qlearn.deserialize_score([1, 2, 3]) is None


def test_serialize_analysis_round_trip():
    analysis = _make_good_analysis()
    serialized = qlearn.serialize_analysis(analysis)
    assert serialized["_format"] == "qianchuan_analysis_v1"
    assert serialized["structure_description"] == analysis.structure_description

    restored = qlearn.deserialize_analysis(serialized)
    assert restored is not None
    assert restored.structure_description == analysis.structure_description
    assert restored.hook_analysis.hook_type == analysis.hook_analysis.hook_type
    assert len(restored.conversion_elements) == len(analysis.conversion_elements)


def test_deserialize_analysis_none():
    assert qlearn.deserialize_analysis(None) is None


def test_deserialize_analysis_bad_string():
    assert qlearn.deserialize_analysis("not valid") is None


def test_deserialize_analysis_wrong_format():
    assert qlearn.deserialize_analysis({"_format": "unknown_v0"}) is None


# ── Tests: feedback aggregation ─────────────────────────────────────────────


def test_aggregate_feedback_empty():
    signal = asyncio.run(qlearn.aggregate_feedback())
    assert signal.iteration_count == 0
    assert signal.improvement_rules == []
    assert "first iteration" in signal.warnings[0]


def test_aggregate_feedback_with_scores():
    signal = asyncio.run(qlearn.aggregate_feedback(existing_scores=[65.0, 72.0, 78.0]))
    assert signal.score_trend == [65.0, 72.0, 78.0]
    assert signal.iteration_count == 0  # no reviews


def test_aggregate_feedback_score_decline():
    signal = asyncio.run(qlearn.aggregate_feedback(existing_scores=[80.0, 75.0, 68.0]))
    assert "Score declined" in signal.improvement_rules[0]


def test_aggregate_feedback_consistently_low():
    signal = asyncio.run(qlearn.aggregate_feedback(existing_scores=[55.0, 60.0, 50.0, 65.0]))
    assert any("consistently below 70" in r for r in signal.improvement_rules)


def test_aggregate_feedback_with_reviews():
    reviews = [
        {
            "reviewer": "小美",
            "score": 72.0,
            "issues": [
                {"severity": "error", "detail": "Audio too loud", "selling_point": "发缝自然"},
                {"severity": "error", "detail": "Color mismatch", "selling_point": "颜色"},
                {"severity": "pass", "detail": "Good hook", "selling_point": "吸睛"},
            ],
        },
        {
            "reviewer": "小美",
            "score": 78.0,
            "issues": [
                {"severity": "error", "detail": "Audio too loud", "selling_point": "稳固"},
                {"severity": "pass", "detail": "Natural hairline", "selling_point": "发缝自然"},
            ],
        },
    ]
    signal = asyncio.run(qlearn.aggregate_feedback(existing_reviews=reviews))
    assert signal.iteration_count == 2
    assert len(signal.common_issues) > 0
    assert len(signal.common_praises) > 0
    assert len(signal.improvement_rules) > 0


def test_aggregate_feedback_bad_json_review():
    """Old-format or corrupt JSON should be skipped with warnings."""
    reviews = [
        "this is not json",
        {"reviewer": "小美", "score": 80.0, "issues": []},
        "also bad json here",
    ]
    signal = asyncio.run(qlearn.aggregate_feedback(existing_reviews=reviews))
    assert signal.iteration_count == 1  # only the valid dict counts
    assert len(signal.warnings) >= 2  # two bad JSON warnings


def test_aggregate_feedback_stringified_reviews():
    """JSON strings representing review objects should be parsed."""
    reviews = [
        json.dumps({"reviewer": "小美", "score": 85.0, "issues": [
            {"severity": "pass", "detail": "Great structure", "selling_point": "结构"}
        ]}),
        json.dumps({"reviewer": "小美", "score": 90.0, "issues": []}),
    ]
    signal = asyncio.run(qlearn.aggregate_feedback(existing_reviews=reviews))
    assert signal.iteration_count == 2


def test_aggregate_feedback_nested_lists():
    """Handles nested lists in review data."""
    reviews = [
        [
            {"reviewer": "小美", "score": 70.0, "issues": []},
            json.dumps({"reviewer": "小美", "score": 75.0, "issues": []}),
        ],
    ]
    signal = asyncio.run(qlearn.aggregate_feedback(existing_reviews=reviews))
    assert signal.iteration_count >= 1


def test_aggregate_feedback_with_segments():
    segments = [
        {"scene_id": 1, "ok": True},
        {"scene_id": 2, "ok": False},
        {"scene_id": 3, "ok": True},
    ]
    signal = asyncio.run(qlearn.aggregate_feedback(existing_segments=segments, existing_scores=[70.0]))
    assert any("rejected segments" in r for r in signal.improvement_rules)


def test_aggregate_feedback_no_issues_in_review():
    """Review with no issues dict should not crash."""
    reviews = [{"reviewer": "小美", "score": 80.0}]
    signal = asyncio.run(qlearn.aggregate_feedback(existing_reviews=reviews))
    assert signal.iteration_count == 1
    assert signal.common_issues == []


def test_aggregate_feedback_non_dict_issues():
    """Non-dict items in issues list should be skipped gracefully."""
    reviews = [{
        "reviewer": "小美",
        "score": 70.0,
        "issues": ["string issue", 123, {"severity": "error", "detail": "ok"}],
    }]
    signal = asyncio.run(qlearn.aggregate_feedback(existing_reviews=reviews))
    assert signal.iteration_count == 1
    # Non-dict items are skipped; dict items count
    assert "ok" in ", ".join(signal.common_issues) if signal.common_issues else True


# ── Tests: schema compatibility ─────────────────────────────────────────────


def test_schema_columns_match_db_fields():
    """Verify that qianchuan_learning uses the same column names as qianchuan_schema."""
    from qianchuan_schema import QIANCHUAN_COLUMNS

    required = {"qianchuan_score", "qianchuan_review", "qianchuan_segments"}
    assert required <= set(QIANCHUAN_COLUMNS), f"Missing columns: {required - set(QIANCHUAN_COLUMNS)}"


def test_serialized_score_fits_schema():
    """Score serialization must produce JSON-serializable dicts compatible with TEXT columns."""
    analysis = _make_good_analysis()
    score = qlearn.score_quality(analysis)
    serialized = qlearn.serialize_score(score)
    # Must be JSON-serializable
    json_str = json.dumps(serialized, ensure_ascii=False)
    assert isinstance(json_str, str)
    assert len(json_str) > 0


@pytest.mark.asyncio
async def test_update_db_feedback():
    """Smoke test: update_db_feedback writes to sqlite without errors."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        con = sqlite3.connect(db_path)
        con.execute(
            """CREATE TABLE clip_groups (
                id INTEGER PRIMARY KEY,
                qianchuan_score REAL,
                qianchuan_review TEXT,
                qianchuan_segments TEXT
            )"""
        )
        con.execute("INSERT INTO clip_groups(id) VALUES(1)")
        con.commit()
        con.close()

        analysis = _make_good_analysis()
        score = qlearn.score_quality(analysis)

        await qlearn.update_db_feedback(db_path, 1, score=score, review={"note": "test"}, segments=[{"OK": True}])

        con = sqlite3.connect(db_path)
        row = con.execute("SELECT qianchuan_score, qianchuan_review, qianchuan_segments FROM clip_groups WHERE id=1").fetchone()
        assert row is not None
        assert row[0] is not None  # score serialized
        assert row[1] is not None  # review serialized
        assert '"OK": true' in row[2]  # segments serialized

        # Verify score can be deserialized from the stored JSON
        restored = qlearn.deserialize_score(row[0])
        assert restored is not None
        assert restored.overall == score.overall
        con.close()
    finally:
        os.unlink(db_path)


# ── Tests: edge cases ──────────────────────────────────────────────────────


def test_dimension_score_defaults():
    dim = qlearn.DimensionScore()
    assert dim.score == 0.0
    assert dim.weight == 0.20
    assert dim.evidence == {}
    assert dim.suggestions == []


def test_hook_analysis_defaults():
    hook = qlearn.HookAnalysis()
    assert hook.hook_type == "unknown"
    assert hook.effectiveness == "unknown"
    assert hook.text_overlay is False


def test_audio_rhythm_bpm_none_handling():
    rhythm = qlearn.AudioRhythm(bpm_estimate=None)
    assert rhythm.bpm_estimate is None


def test_feedback_signal_defaults():
    signal = qlearn.FeedbackSignal()
    assert signal.iteration_count == 0
    assert signal.score_trend == []
    assert signal.improvement_rules == []


def test_safe_str_list():
    assert qlearn._safe_str_list(None) == []
    assert qlearn._safe_str_list("not a list") == []
    assert qlearn._safe_str_list([1, 2, "three"]) == ["1", "2", "three"]


def test_safe_segments():
    assert qlearn._safe_segments(None) == []
    assert qlearn._safe_segments("not a list") == []
    assert qlearn._safe_segments([{"start_s": 0.0}]) == [{"start_s": 0.0, "end_s": 0.0, "type": "", "description": "", "key_frames": ""}]


def test_all_dataclasses_importable():
    """Ensure all exported dataclasses can be imported."""
    classes = [
        qlearn.VideoAnalysis,
        qlearn.HookAnalysis,
        qlearn.VisualStyle,
        qlearn.AudioRhythm,
        qlearn.ConversionElement,
        qlearn.AudienceAdaptation,
        qlearn.ReusablePattern,
        qlearn.QualityScore,
        qlearn.DimensionScore,
        qlearn.FeedbackSignal,
    ]
    for cls in classes:
        instance = cls()
        assert instance is not None, f"Failed to instantiate {cls.__name__}"
