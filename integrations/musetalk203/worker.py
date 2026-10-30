from pathlib import Path
import sys,json,os,re,subprocess
ROOT=Path(r'F:\aid-models\musetalk-1.5')
FFMPEG=r'C:\ProgramData\chocolatey\bin\ffmpeg.exe'
def main(jp):
 j=json.loads(jp.read_text(encoding='utf-8'))
 if j.get('profile')!='musetalk-15-203':raise ValueError('Wrong profile')
 r=j['payload']['lipSyncRequest']
 if set(r)-{'inputArtifactId','audioArtifactId','startSeconds','durationSeconds','qualityMode'}:raise ValueError('Unsupported fields')
 mode=r.get('qualityMode','baseline')
 if mode not in ('baseline','localized'):raise ValueError('Unsupported quality mode')
 def artifact(k):
  a=r[k]
  if not re.fullmatch('[a-f0-9]{32}',a):raise ValueError('Invalid artifact')
  p=Path(j['artifacts'][a]).resolve(strict=True)
  if not p.is_file():raise ValueError('Missing artifact')
  return p
 source=artifact('inputArtifactId');audio=artifact('audioArtifactId');start=float(r['startSeconds']);duration=float(r['durationSeconds'])
 if not (0<=start<=3600 and 5<=duration<=15):raise ValueError('Invalid window')
 info=json.loads(subprocess.check_output([str(Path(FFMPEG).with_name('ffprobe.exe')),'-v','error','-show_entries','format=duration','-of','json',str(audio)]))
 audio_duration=float(info['format']['duration'])
 if not 5<=audio_duration<=min(15,duration+0.1):raise ValueError('Audio must fit source window')
 work=jp.parent/('musetalk-'+jp.stem);work.mkdir(exist_ok=True)
 ff=Path(FFMPEG)
 os.environ['PATH']=str(ff.parent)+os.pathsep+os.environ['PATH']
 def run(cmd,cwd=None):subprocess.run(cmd,cwd=cwd,check=True,stdout=sys.stderr,stderr=sys.stderr,timeout=2400)
 video=work/'source.mp4'
 run([str(ff),'-y','-v','error','-ss',str(start),'-i',str(source),'-t',str(duration),'-vf','fps=25','-an','-c:v','libx264','-crf','18',str(video)])
 config=work/'inference.json';config.write_text(json.dumps({'pilot':{'video_path':video.as_posix(),'audio_path':audio.as_posix(),'result_name':'musetalk-pilot.mp4'}}))
 run([str(ROOT/'venv/Scripts/python.exe'),'-m',('scripts.inference_localized' if mode=='localized' else 'scripts.inference'),'--inference_config',str(config),'--result_dir',str(work/'result'),'--unet_model_path','models/musetalkV15/unet.pth','--unet_config','models/musetalkV15/musetalk.json','--version','v15','--batch_size','2','--use_float16'],ROOT/'repo')
 output=work/'result/v15/musetalk-pilot.mp4'
 if not output.exists() or output.stat().st_size<10000:raise RuntimeError('MuseTalk returned no output; inspect inference error')
 print(json.dumps({'localOutputRef':str(output),'filename':output.name,'contentType':'video/mp4','previewOnly':True,'model':'MuseTalk1.5','qualityMode':mode,'nodeId':'gpu-203'}))
if __name__=='__main__':main(Path(sys.argv[1]))
