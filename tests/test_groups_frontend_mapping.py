from pathlib import Path


GROUPS_VIEW = Path(__file__).parents[1] / "frontend/src/views/Groups.vue"
API_MODULE = Path(__file__).parents[1] / "frontend/src/api.js"


def test_five_version_controls_use_independent_retry_endpoints():
    view = GROUPS_VIEW.read_text()
    api = API_MODULE.read_text()

    assert "if (version === 'classic') await mergeGroup(group.id)" in view
    assert "else if (version === 'director') await retryDirector(group.id)" in view
    assert "else if (version === 'qianchuan') await retryQianchuan(group.id)" in view
    assert "else await retryStyles(group.id, version)" in view
    assert "body = version ? JSON.stringify({ version }) : undefined" in api
    assert "`${BASE}/api/groups/${id}/retry-director`" in api
    assert "`${BASE}/api/groups/${id}/retry-qianchuan`" in api


def test_classic_readiness_uses_merge_artifact_fields():
    view = GROUPS_VIEW.read_text()

    assert "function classicStatus(group)" in view
    assert "Number(group.merge_status ?? group.classic_status ?? 0)" in view
    assert "Boolean(group.merged_filename)" in view
    assert "group.classic_available !== false" in view
