from pathlib import Path
from unittest.mock import patch
from backend.group_artifact_snapshot import GroupArtifactSnapshot


def test_deduplicates_real_file_checks_and_refreshes_next_request(tmp_path):
    (tmp_path/'video.mp4').write_bytes(b'video')
    (tmp_path/'directory.mp4').mkdir()
    candidates = lambda value: [tmp_path/value]
    snapshot = GroupArtifactSnapshot(['classic', 'codex'], candidates)
    stat=Path.is_file
    with patch.object(Path, 'is_file', autospec=True, side_effect=stat) as check:
        for _ in range(20):
            assert snapshot.resolve('video.mp4', 'codex') == (str(tmp_path/'video.mp4'), 'ready')
            assert snapshot.resolve('missing.mp4', 'classic') == (None, 'stale_path')
            assert snapshot.resolve('directory.mp4', 'classic') == (None, 'stale_path')
        assert check.call_count == 3
    assert snapshot.resolve(None, 'classic') == (None, 'not_generated')
    assert snapshot.resolve('video.mp4', 'unknown') == (None, 'invalid_version')
    (tmp_path/'video.mp4').unlink()
    assert GroupArtifactSnapshot(['codex'], candidates).resolve('video.mp4','codex') == (None,'stale_path')


def test_denied_path_does_not_hide_fallback_or_other_groups(tmp_path):
    good=tmp_path/'good';good.mkdir();(good/'video.mp4').write_bytes(b'x')
    denied=tmp_path/'denied';stat=Path.is_file
    def guarded_stat(path):
        if path.parent==denied:raise PermissionError('share denied')
        return stat(path)
    with patch.object(Path,'is_file',guarded_stat):
        snapshot=GroupArtifactSnapshot(['classic'],lambda value:[denied/value,good/value],values=['video.mp4','bad.mp4','video.mp4'])
        assert snapshot.resolve('video.mp4','classic') == (str(good/'video.mp4'),'ready')
        assert snapshot.resolve('bad.mp4','classic') == (None,'access_error')
        assert len(snapshot.results)==2
