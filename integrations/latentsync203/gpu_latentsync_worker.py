"""Fixed 203 lip-sync pilot adapter. Input artifact + bounded text, no commands."""
from pathlib import Path
import argparse,json,os,re,subprocess,sys,urllib.request,wave,time,shutil
ROOT=Path(r'F:\aid-models\latentsync-1.5')
PROFILE='latentsync-15-203'
FFMPEG=r'C:\ProgramData\chocolatey\bin\ffmpeg.exe'
FFPROBE=r'C:\ProgramData\chocolatey\bin\ffprobe.exe'

def validate(job):
    if job.get('profile')!=PROFILE:raise ValueError('wrong profile')
    r=job.get('payload',{}).get('lipSyncRequest',{})
    if set(r)-{'inputArtifactId','startSeconds','durationSeconds','text','referenceText'}:raise ValueError('unsupported fields')
    aid=r.get('inputArtifactId','')
    if not re.fullmatch('[a-f0-9]{32}',aid):raise ValueError('invalid artifact')
    source=Path(job.get('artifacts',{}).get(aid,'')).resolve(strict=True)
    if not source.is_file():raise ValueError('missing artifact')
    start=float(r.get('startSeconds',0));duration=float(r.get('durationSeconds',12))
    if not (0<=start<=3600 and 5<=duration<=15):raise ValueError('invalid clip window')
    text=r.get('text','').strip()
    if not 5<=len(text)<=100:raise ValueError('text must be 5-100 characters')
    return source,start,duration,text,str(r.get('referenceText',''))[:500]

def main(job_file):
    source,start,duration,text,reference_text=validate(json.loads(job_file.read_text(encoding='utf-8')))
    work=job_file.parent/('lipsync-'+job_file.stem);work.mkdir(exist_ok=True)
    cancel=Path(os.environ.get('GPU_JOB_CANCEL_FILE',str(job_file)+'.cancel'))
    def run(cmd,cwd=None):
        if cancel.exists():raise RuntimeError('cancelled')
        subprocess.run(cmd,cwd=cwd,stdout=sys.stderr,stderr=sys.stderr,check=True,timeout=2400)
    video=work/'source.mp4';ref=work/'reference.wav'
    run([FFMPEG,'-y','-v','error','-ss',str(start),'-i',str(source),'-t',str(duration),'-vf','fps=25,scale=-2:720','-c:v','libx264','-preset','fast','-crf','18','-an',str(video)])
    run([FFMPEG,'-y','-v','error','-ss',str(start),'-i',str(source),'-t',str(duration),'-vn','-ar','24000','-ac','1',str(ref)])
    sys.path.insert(0,r'C:\ProgramData\AIDGpuScheduler')
    import gpu_remote_omnivoice_worker as tts
    result=tts.execute({'text':text,'reference':ref,'referenceText':reference_text,'speed':1.0,'filename':'pilot-voice.wav'},job_file,cancel)
    audio=Path(result['localOutputRef'])
    req=urllib.request.Request('http://127.0.0.1:8879/api/gpu/release',method='POST')
    with urllib.request.urlopen(req,timeout=60) as r:released=json.load(r)
    if released.get('status') != 'released':raise RuntimeError('TTS release not confirmed')
    with wave.open(str(audio)) as w:audio_seconds=w.getnframes()/w.getframerate()
    if not 5<=audio_seconds<=min(18,duration+3):raise RuntimeError('Generated speech length outside pilot range')
    if audio_seconds < 10:
        paced=work/'paced-voice.wav'
        run([FFMPEG,'-y','-v','error','-i',str(audio),'-af',f'atempo={audio_seconds/10:.6f}',str(paced)])
        audio=paced;audio_seconds=10.0
    # Pad a brief freeze only when audio slightly exceeds the source, never loop gestures.
    padded=work/'input.mp4'
    run([FFMPEG,'-y','-v','error','-i',str(video),'-vf','tpad=stop_mode=clone:stop_duration=3','-t',str(audio_seconds),'-c:v','libx264','-crf','18',str(padded)])
    output=work/'lipsync-pilot.mp4'
    os.environ['PATH']=str(Path(FFMPEG).parent)+os.pathsep+os.environ['PATH']
    os.environ['HF_HOME']=str(ROOT/'hf-cache')
    run([str(ROOT/'venv/Scripts/python.exe'),'-m','scripts.inference','--unet_config_path','configs/unet/stage2.yaml','--inference_ckpt_path','checkpoints/latentsync_unet.pt','--video_path',str(padded),'--audio_path',str(audio),'--video_out_path',str(output),'--inference_steps','20','--guidance_scale','1.5','--seed','42'],cwd=ROOT/'repo')
    if not output.is_file() or output.stat().st_size<10000:raise RuntimeError('Missing rendered result')
    info=json.loads(subprocess.check_output([FFPROBE,'-v','error','-show_entries','format=duration','-of','json',str(output)]))
    print(json.dumps({'localOutputRef':str(output),'filename':output.name,'contentType':'video/mp4','model':'LatentSync-1.5','nodeId':'gpu-203','duration':info['format']['duration'],'text':text,'previewOnly':True}))
if __name__=='__main__':main(Path(sys.argv[1]))
