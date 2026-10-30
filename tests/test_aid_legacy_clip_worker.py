import importlib.util
from pathlib import Path
import pytest
p=Path(__file__).parents[1]/'integrations/aid/legacy_clip_worker.py'
s=importlib.util.spec_from_file_location('legacy',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def job(tmp_path):
    path=tmp_path/'source.mp4';path.write_bytes(b'owned source')
    clip=dict(inputArtifactId='a'*32,startSeconds=10,durationSeconds=20,muteSpans=[[1,2]])
    req=dict(renderMode=m.MODE,clips=[clip,dict(clip,startSeconds=50)],assContent='[Script Info]\n[Events]\nDialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,测试',outputFilename='retry.mp4')
    return dict(profile='qianchuan-render',payload={'qianchuanRenderRequest':req},artifacts={'a'*32:str(path)})
def test_validated_owned_timeline_and_fixed_commands(tmp_path):
    request=m.validate(job(tmp_path));assert request['duration']==39.65
    cmd=m.normalize_command(request['clips'][0],tmp_path/'part.mp4',1440,2560,True,True)
    assert 'aeval=' in cmd[cmd.index('-af')+1];assert '-gpu' in cmd
    composed=m.compose_command(request,[Path('a'),Path('b')],Path('out'))
    assert 'offset=19.650000' in composed[composed.index('-filter_complex')+1]
    assert 'subtitles=' in ' '.join(m.subtitle_command(Path('video'),tmp_path/'captions.ass',Path('out')))
@pytest.mark.parametrize('change',[{'command':'bad'},{'maxDurationSeconds':10},{'preserveAudio':'yes'},{'outputFilename':'../bad.mp4'},{'assContent':'[Script Info]\n[Events]\n[Fonts]'}])
def test_invalid_or_unbounded_requests_rejected(tmp_path,change):
    j=job(tmp_path);j['payload']['qianchuanRenderRequest'].update(change)
    with pytest.raises((ValueError,AssertionError)):m.validate(j)
def test_clip_nan_unsupported_transition_and_missing_artifact(tmp_path):
    for change in [{'startSeconds':float('nan')},{'transition':'custom-filter'},{'muteSpans':[[2,1]]},{'inputArtifactId':'b'*32}]:
        j=job(tmp_path);j['payload']['qianchuanRenderRequest']['clips'][0].update(change)
        with pytest.raises((ValueError,AssertionError)):m.validate(j)
