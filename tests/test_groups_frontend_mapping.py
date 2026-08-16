from pathlib import Path


GROUPS_VIEW = Path(__file__).parents[1] / "frontend/src/views/Groups.vue"
API_MODULE = Path(__file__).parents[1] / "frontend/src/api.js"


def test_five_version_controls_use_independent_retry_endpoints():
    view = GROUPS_VIEW.read_text()
    api = API_MODULE.read_text()

    assert "if (version === 'classic') await mergeGroup(group.id)" in view
    assert "else if (version === 'director') await retryDirector(group.id)" in view
    assert "else if (version === 'qianchuan') await retryQianchuan(group.id)" in view
    assert "else await retryStyle(group.id, version)" in view
    assert "body: JSON.stringify({ version })," in api
    assert "/retry-director`" in api
    assert "/retry-qianchuan`" in api


def test_classic_readiness_uses_merge_artifact_fields():
    view = GROUPS_VIEW.read_text()

    assert "function versionStatus(group, version) {\n  if (version === 'classic') return Number(group.merge_status ?? 0)" in view
    assert "Boolean(group.merged_filename)" in view
    assert "group.classic_file_status === 'ready'" in view
