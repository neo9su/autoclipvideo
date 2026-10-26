"""Proposed fixed AID worker extension. No SSH, API keys, or client command surface.

Not deployed: imported only by the approved qianchuan-render node executor.
"""
from pathlib import Path
import math,re,shutil,time

MODE='legacy_clip_v1'
TRANSITIONS={'fade','dissolve','wipeleft','wiperight','slideleft','slideright','circleopen','circleclose','smoothleft','smoothright'}
KEYS={'renderMode','clips','aspectRatio','maxDurationSeconds','preserveAudio','outputFilename','assContent'}
CLIP_KEYS={'inputArtifactId','startSeconds','durationSeconds','transition','transitionDuration','muteSpans'}

def number(value,low,high,name):
    if isinstance(value,bool):raise ValueError(name+' must be numeric')
    value=float(value)
    if not math.isfinite(value) or not low<=value<=high:raise ValueError(name+' is out of range')
    return value

def validate(job):
    assert job.get('profile')=='qianchuan-render','Wrong profile'
    raw=job.get('payload',{}).get('qianchuanRenderRequest',{})
    if not isinstance(raw,dict) or raw.get('renderMode')!=MODE or set(raw)-KEYS:raise ValueError('Unsupported legacy render request')
    clips=raw.get('clips')
    if not isinstance(clips,list) or not 1<=len(clips)<=180:raise ValueError('Expected 1..180 clips')
    aspect=raw.get('aspectRatio','9:16')
    if aspect not in {'9:16','16:9'}:raise ValueError('Unsupported aspect ratio')
    preserve=raw.get('preserveAudio',True)
    if not isinstance(preserve,bool):raise ValueError('preserveAudio must be boolean')
    ass=raw.get('assContent','')
    if not isinstance(ass,str) or not ass.strip() or len(ass.encode('utf8'))>1_000_000:raise ValueError('A bounded ASS subtitle document is required')
    if '[Script Info]' not in ass or '[Events]' not in ass:raise ValueError('Invalid ASS document')
    if any(x in ass.casefold() for x in ['[fonts]','[graphics]']):raise ValueError('Embedded subtitle attachments are unsupported')
    result=[]
    for item in clips:
        if not isinstance(item,dict) or set(item)-CLIP_KEYS:raise ValueError('Unsupported clip fields')
        aid=str(item.get('inputArtifactId',''))
        if not re.fullmatch('[a-f0-9]{32}',aid):raise ValueError('Invalid artifact identifier')
        mapped=job.get('artifacts',{}).get(aid)
        if not mapped:raise ValueError('Missing owned artifact mapping')
        path=Path(mapped).resolve(strict=True)
        if not path.is_file():raise ValueError('Artifact is not a file')
        start=number(item.get('startSeconds',0),0,86400,'start')
        duration=number(item.get('durationSeconds',0),.05,299,'duration')
        transition=item.get('transition','dissolve')
        if transition not in TRANSITIONS:raise ValueError('Unsupported transition')
        td=number(item.get('transitionDuration',.35),0,2,'transitionDuration')
        spans=item.get('muteSpans',[])
        if not isinstance(spans,list) or len(spans)>100:raise ValueError('Too many mute spans')
        valid=[]
        for pair in spans:
            if not isinstance(pair,list) or len(pair)!=2:raise ValueError('Malformed mute span')
            a=number(pair[0],0,duration,'mute start');b=number(pair[1],0,duration,'mute end')
            if b<=a:raise ValueError('Empty mute span')
            valid.append((a,b))
        result.append(dict(path=path,start=start,duration=duration,transition=transition,transitionDuration=td,muteSpans=valid))
    overlaps=[min(c['transitionDuration'],c['duration']/2,result[i+1]['duration']/2) for i,c in enumerate(result[:-1])]
    total=sum(c['duration'] for c in result)-sum(overlaps)
    maximum=number(raw.get('maxDurationSeconds',299),4,299,'maximum')
    if total<4 or total>maximum+.001:raise ValueError('Result duration exceeds limits')
    filename=str(raw.get('outputFilename','legacy-retry.mp4'))
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,159}\.mp4',filename):raise ValueError('Unsafe output filename')
    return dict(renderMode=MODE,clips=result,overlaps=overlaps,duration=total,preserveAudio=preserve,aspect=aspect,assContent=ass,filename=filename)

def dimensions(request):return (1440,2560) if request['aspect']=='9:16' else (2560,1440)

def encode_options():
    return ['-c:v','h264_nvenc','-gpu','0','-preset','p4','-pix_fmt','yuv420p','-b:v','10000k','-maxrate','10000k','-bufsize','20000k','-c:a','aac','-b:a','192k','-ar','48000','-ac','2']

def normalize_command(clip,output,width,height,has_audio,preserve):
    cmd=['/usr/bin/ffmpeg','-hide_banner','-loglevel','error','-y','-ss',f"{clip['start']:.6f}",'-t',f"{clip['duration']:.6f}",'-i',str(clip['path'])]
    if not (has_audio and preserve):
        cmd+=['-f','lavfi','-t',f"{clip['duration']:.6f}",'-i','anullsrc=r=48000:cl=stereo']
    cmd+=['-map','0:v:0','-map','0:a:0' if has_audio and preserve else '1:a:0','-vf',f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,settb=1/30,format=yuv420p']
    audio='aformat=channel_layouts=stereo:sample_rates=48000,asetpts=PTS-STARTPTS'
    if clip['muteSpans'] and preserve:
        condition='+'.join(f'between(t,{a:.6f},{b:.6f})' for a,b in clip['muteSpans'])
        expressions=[f"if(gt({condition},0),0.12*sin(2*PI*1000*t),val({channel}))" for channel in range(2)]
        audio+=",aeval='"+'|'.join(expressions)+"'"
    cmd+=['-af',audio]+encode_options()+['-movflags','+faststart',str(output)]
    return cmd

def compose_command(request,paths,output):
    cmd=['/usr/bin/ffmpeg','-hide_banner','-loglevel','error','-y']
    for path in paths:cmd+=['-i',str(path)]
    filters=[];video='[0:v]';audio='[0:a]';cursor=request['clips'][0]['duration']
    for i,overlap in enumerate(request['overlaps'],1):
        v=f'[v{i}]';a=f'[a{i}]'
        if overlap:
            filters.append(f"{video}[{i}:v]xfade=transition={request['clips'][i-1]['transition']}:duration={overlap:.6f}:offset={cursor-overlap:.6f}{v}")
            filters.append(f'{audio}[{i}:a]acrossfade=d={overlap:.6f}:c1=tri:c2=tri{a}')
        else:
            filters.append(f'{video}{audio}[{i}:v][{i}:a]concat=n=2:v=1:a=1{v}{a}')
        video,audio=v,a;cursor+=request['clips'][i]['duration']-overlap
    if filters:cmd+=['-filter_complex_threads','1','-filter_complex',';'.join(filters),'-map',video,'-map',audio]
    else:cmd+=['-map','0:v:0','-map','0:a:0']
    return cmd+encode_options()+['-movflags','+faststart',str(output)]

def subtitle_command(source,ass,output):
    path=str(ass).replace('\\','\\\\').replace(':','\\:').replace("'", "'\\''")
    return ['/usr/bin/ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(source),'-map','0:v:0','-map','0:a:0','-vf',f"subtitles=filename='{path}'"]+encode_options()+['-movflags','+faststart',str(output)]

def execute(request,job_file,cancel_file,run,probe):
    job_file=Path(job_file);work=job_file.parent/'legacy-clip-work';work.mkdir(exist_ok=False)
    result_dir=job_file.parent/'results';result_dir.mkdir(exist_ok=True)
    output=result_dir/request['filename'];started=time.monotonic();deadline=started+3600
    width,height=dimensions(request)
    try:
        paths=[]
        for i,clip in enumerate(request['clips']):
            meta=probe(clip['path'])
            if clip['start']+clip['duration']>float(meta['durationSeconds'])+.2:raise ValueError('Clip exceeds source duration')
            path=work/f'part-{i:03d}.mp4';run(normalize_command(clip,path,width,height,meta['hasAudio'],request['preserveAudio']),cancel_file,deadline);paths.append(path)
        assembled=work/'assembled.mp4';run(compose_command(request,paths,assembled),cancel_file,deadline)
        ass=work/'captions.ass';ass.write_text(request['assContent'],encoding='utf-8-sig')
        staged=work/'captioned.mp4';run(subtitle_command(assembled,ass,staged),cancel_file,deadline)
        video=probe(staged)
        if (video['width'],video['height'])!=(width,height) or not video['hasAudio']:raise RuntimeError('Unexpected rendered media tracks')
        if abs(video['durationSeconds']-request['duration'])>.3:raise RuntimeError('Rendered timeline differs from requested timeline')
        staged.replace(output)
        return dict(localOutputRef=str(output),filename=output.name,contentType='video/mp4',nodeId='gpu-222',renderMode=MODE,clipCount=len(paths),video=video,elapsedSeconds=round(time.monotonic()-started,3))
    finally:shutil.rmtree(work,ignore_errors=True)
