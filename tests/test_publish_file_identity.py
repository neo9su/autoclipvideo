from pathlib import Path
import importlib.util

import pytest
from backend import video_path_resolver as resolver


@pytest.fixture
def media(tmp_path, monkeypatch):
    root=tmp_path/'recordings';root.mkdir()
    monkeypatch.setattr(resolver,'RECORDINGS_DIR',root)
    monkeypatch.setattr(resolver,'PROJECT_ROOT',tmp_path)
    if hasattr(resolver,'_DEFAULT_RECORDINGS_PATHS'):monkeypatch.setattr(resolver,'_DEFAULT_RECORDINGS_PATHS',[root])
    def make(name):
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(name.encode());return str(p)
    return make


def test_existing_task_file_wins_over_other_group_versions(media):
    chosen=media('realistic/selected.mp4');other=media('qianchuan/different.mp4')
    path,_=resolver.resolve_video_path(chosen,{'realistic_final_video':chosen,'qianchuan_final_video':other})
    assert path==chosen


def test_missing_task_file_cannot_borrow_another_version(media):
    other=media('qianchuan/other.mp4')
    path,reason=resolver.resolve_video_path('missing-selected.mp4',{'qianchuan_final_video':other})
    assert path is None and reason=='stale_path'


def test_migration_can_recover_the_same_filename(media):
    chosen=media('selected.mp4');other=media('other.mp4')
    path,_=resolver.resolve_video_path(r'C:\old_recordings\selected.mp4',{'qianchuan_final_video':other})
    assert path==chosen


def test_nested_migration_uses_only_matching_group_filename(media):
    chosen=media('nested/selected.mp4');other=media('other.mp4')
    path,_=resolver.resolve_video_path('/old/selected.mp4',{'director_final_video':chosen,'qianchuan_final_video':other})
    assert path==chosen


def test_ambiguous_missing_basename_is_not_guessed(media):
    first=media('realistic/clip.mp4');second=media('director/clip.mp4')
    path,reason=resolver.resolve_video_path('/old/clip.mp4',{'realistic_final_video':first,'director_final_video':second})
    assert path is None and reason=='ambiguous_path'


def test_legacy_version_literal_stays_in_that_version(media):
    chosen=media('realistic/chosen.mp4');other=media('qianchuan/other.mp4')
    group={'realistic_final_video':chosen,'qianchuan_final_video':other}
    assert resolver.resolve_video_path('realistic',group)[0]==chosen
    assert resolver.resolve_video_path('conservative',group)[0] is None


def test_default_without_selection_can_choose_available_version(media):
    other=media('other.mp4')
    assert resolver.resolve_video_path(None,{'qianchuan_final_video':other})[0]==other


def test_explicit_missing_version_does_not_fallback(media):
    other=media('other.mp4')
    path,version,_,available=resolver.resolve_publish_video({'qianchuan_final_video':other},'realistic')
    assert path is None and version is None and 'qianchuan' in available


def test_invalid_version_does_not_choose_default(media):
    assert resolver.resolve_publish_video({'merged_filename':media('classic.mp4')},'typo')[0] is None
