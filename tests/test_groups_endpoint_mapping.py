"""Regression checks for the independent five-version Groups controls."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GROUPS_SOURCE = (ROOT / "frontend/src/views/Groups.vue").read_text()
API_SOURCE = (ROOT / "frontend/src/api.js").read_text()


def test_five_version_controls_use_independent_endpoints():
    trigger_source = GROUPS_SOURCE[GROUPS_SOURCE.index("async function triggerVersion"):]
    assert "if (version === 'classic') await mergeGroup(group.id)" in trigger_source
    assert "else if (version === 'director') await retryDirector(group.id)" in trigger_source
    assert "else if (version === 'qianchuan') await retryQianchuan(group.id)" in trigger_source
    assert "else await retryStyles(group.id, version)" in trigger_source
    assert "当前接口会同时提交直出版与保守版" not in trigger_source

    assert "/retry-director" in API_SOURCE
    assert "/retry-qianchuan" in API_SOURCE
    assert "JSON.stringify({ version })" in API_SOURCE


def test_classic_readiness_uses_merge_artifact_fields():
    assert "group.merge_status ?? group.classic_status" in GROUPS_SOURCE
    assert "Boolean(group.merged_filename)" in GROUPS_SOURCE
