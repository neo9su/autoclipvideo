"""CPU-only filter-graph smoke test; does not validate NVENC/GPU deployment."""
import importlib.util,json,shutil,subprocess
from pathlib import Path
import pytest
p=Path(__file__).parents[1]/'integrations/aid/legacy_clip_worker.py'
s=importlib.util.spec_from_file_location('worker_smoke',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

def test_real_transition_beep_and_ass_filter_graph(tmp_path,monkeypatch):
    ffmpeg=shutil.which('ffmpeg');ffprobe=shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:pytest.skip('Local CPU media tools unavailable')
    filters=subprocess.run([ffmpeg,'-hide_banner','-filters'],capture_output=True,text=True,timeout=10)
    if not any(' subtitles ' in line for line in filters.stdout.splitlines()):pytest.skip('Local ffmpeg lacks libass; full CPU test runs on 203')
    source=tmp_path/'source.mp4'
    subprocess.run([ffmpeg,'-loglevel','error','-f','lavfi','-i','testsrc2=size=144x256:rate=30','-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','8','-c:v','libx264','-preset','ultrafast','-c:a','aac',str(source)],check=True,timeout=30)
    ass='''[Script Info]
ScriptType: v4.00+
PlayResX: 144
PlayResY: 256
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,16,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,5,5,10,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:05.00,Default,,0,0,0,,Caption test
'''
    j=dict(profile='qianchuan-render',artifacts={'a'*32:str(source)},payload={'qianchuanRenderRequest':dict(renderMode=m.MODE,clips=[dict(inputArtifactId='a'*32,startSeconds=0,durationSeconds=3,muteSpans=[[1,2]]),dict(inputArtifactId='a'*32,startSeconds=4,durationSeconds=3)],assContent=ass,outputFilename='smoke.mp4')})
    req=m.validate(j);monkeypatch.setattr(m,'dimensions',lambda _:(144,256))
    def run(command,*_):
        command=list(command);command[0]=ffmpeg
        at=command.index('-gpu');del command[at:at+2]
        command[command.index('h264_nvenc')]='libx264';command[command.index('-preset')+1]='ultrafast'
        command[1:1]=['-threads','2','-filter_threads','1']
        result=subprocess.run(command,capture_output=True,timeout=40)
        assert result.returncode==0,result.stderr.decode(errors='replace')[-2500:]
    def probe(path):
        result=subprocess.run([ffprobe,'-v','error','-show_entries','stream=codec_type,width,height:format=duration','-of','json',str(path)],check=True,capture_output=True,timeout=10)
        data=json.loads(result.stdout);v=next(x for x in data['streams'] if x['codec_type']=='video')
        return dict(width=v['width'],height=v['height'],hasAudio=any(x['codec_type']=='audio' for x in data['streams']),durationSeconds=float(data['format']['duration']))
    result=m.execute(req,tmp_path/'job.json',tmp_path/'cancel',run,probe)
    assert result['video']['hasAudio'];assert abs(result['video']['durationSeconds']-5.65)<.3
    assert Path(result['localOutputRef']).is_file()
