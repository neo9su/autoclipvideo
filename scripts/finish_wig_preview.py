"""CPU-only, versioned 2K subtitle/highlight preview. Never publishes or changes DB."""
from pathlib import Path
import argparse
import hashlib
import json
import math
import re
import struct
import subprocess
import wave
from PIL import Image, ImageDraw, ImageFont

FONT=Path('/Users/work/1-codex/2-codex-capcut/assets/fonts/WenYueXinQingNian-W8.otf')

def stamp(t,ass=False):
    unit=100 if ass else 1000;n=round(t*unit);h,n=divmod(n,3600*unit);m,n=divmod(n,60*unit);s,n=divmod(n,unit)
    return f'{h}:{m:02}:{s:02}.{n:02}' if ass else f'{h:02}:{m:02}:{s:02},{n:03}'

def sec(text):
    h,m,s=text.replace(',','.').split(':');return int(h)*3600+int(m)*60+float(s)

def run(root):
    source=root/'recording-45409-brown-fringe-preview-v1.mp4'
    assert hashlib.sha256(source.read_bytes()).hexdigest()=='bccade1d5c3fac34d86b9888c4ad3ffdd681a88accbf1341302187876bc39bfa'
    assert FONT.is_file()
    dest=root/'styled-preview-v4';dest.mkdir(exist_ok=True)
    # Correct only obvious common-word homophones. Ambiguous phrases are retained in the audit, not invented.
    fixes={'特别的减零':'特别的减龄','不会露脚':'不会露角','女大学生的及时感':'女大学生的既视感'}
    uncertain={14,15,18,24,35,38,39,40,48}
    cues=[];audit=[]
    for block in re.split(r'\n\s*\n',(root/'recording-45409-brown-fringe-preview-v1.srt').read_text(encoding='utf-8')):
        lines=block.strip().splitlines()
        if len(lines)<3:continue
        index=int(lines[0]);a,b=map(sec,lines[1].split(' --> '));text=''.join(lines[2:])
        if a >= 44.22:
            continue
        a += 1.0; b = min(b,44.22)+1.0
        if index in uncertain:
            audit.append({'index':index,'start':a,'end':b,'raw_text':text,'status':'requires_listening_not_burned'})
            continue
        text=fixes.get(text,text)
        cues.append({'start':a,'end':b,'text':text})
    duration=45.22
    shots=[(35.3,1,'先看半扎效果'),(20,1,'侧面轮廓'),(30,1,'背面展示'),(10,1,'齐刘海'),(0,1,'长直发半扎')]
    titles=[(0,1,shots[0][2]),(1,2,shots[1][2]),(2,3,shots[2][2]),(3,4,shots[3][2]),(4,5,shots[4][2]),
            (5,10,'半扎效果展示'),(10,15,'正面与发色'),(15,20,'换个角度看发色'),(20,29.3,'侧面头型展示'),(29.3,36,'再看背面效果'),(36,45.22,'远距离看整体')]
    points=sorted({0,duration,*[t for c in cues for t in (c['start'],c['end'])],*[t for a,b,_ in titles for t in (a,b)]})
    font=ImageFont.truetype(str(FONT),82);headline=ImageFont.truetype(str(FONT),120)
    def draw_center(d,text,y,f,fill,stroke,width):
        bounds=d.textbbox((0,0),text,font=f,stroke_width=width);x=(1440-(bounds[2]-bounds[0]))/2-bounds[0]
        d.text((x,y),text,font=f,fill=fill,stroke_width=width,stroke_fill=stroke)
    pieces=[]
    for i,(a,b) in enumerate(zip(points,points[1:])):
        middle=(a+b)/2;im=Image.new('RGBA',(1440,2560));d=ImageDraw.Draw(im)
        for x,y,text in titles:
            if x<=middle<y:draw_center(d,text,90,headline,'#ffdf00','white',7)
        for c in cues:
            if c['start']<=middle<c['end']:
                text=c['text'];lines=[text] if len(text)<=16 else [text[:len(text)//2],text[len(text)//2:]]
                for j,line in enumerate(lines):draw_center(d,line,1910+j*105,font,'white','black',6)
        png=dest/f'overlay-{i:03}.png';im.save(png);pieces.append((png.name,b-a))
    concat=dest/'overlays.ffconcat';concat.write_text('ffconcat version 1.0\n'+''.join(f"file '{name}'\nduration {d:.6f}\n" for name,d in pieces)+f"file '{pieces[-1][0]}'\n")
    ding=dest/'ding.wav';sr=48000
    with wave.open(str(ding),'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(sr)
        samples=[]
        for i in range(round(sr*.52)):
            t=i/sr;v=0
            for delay,freq in [(0,1568),(.17,2093)]:
                x=t-delay
                if x>=0:v+=.05*(1-math.exp(-x*900))*math.exp(-x*14)*math.sin(2*math.pi*freq*x)
            samples.append(struct.pack('<h',round(v*32767)))
        f.writeframes(b''.join(samples))
    chunks=[f'[0:v]trim=start={start}:duration={dur},setpts=PTS-STARTPTS[v{i}]' for i,(start,dur,_) in enumerate(shots)]
    chunks+=['[0:v]trim=start=4:end=44.22,setpts=PTS-STARTPTS[v5]',
             ''.join(f'[v{i}]' for i in range(6))+'concat=n=6:v=1:a=0,fps=30[video]',
             '[video][1:v]overlay=0:0:eof_action=pass:repeatlast=1[v]',
             '[0:a]atrim=end=44.22,asetpts=PTS-STARTPTS,adelay=1000:all=1[voice]', '[2:a]asplit=3[d0][d1][d2]',
             '[d0]adelay=800:all=1[b0]', '[d1]adelay=2800:all=1[b1]', '[d2]adelay=20000:all=1[b2]',
             '[voice][b0][b1][b2]amix=inputs=4:duration=first:normalize=0,alimiter=limit=0.95:level=0[a]']
    output=dest/'棕色_齐刘海_长直发_半扎演示_字幕高光预览v4.mp4'
    manifest={'source_recording':45409,'source_start':427.37,'source_end':471.59,'product_id':None,'name_status':'feature_name_only',
              'opening_shots':[{'source_start':427.37+a,'duration':b,'label':c} for a,b,c in shots],
              'body_source_range':[431.37,471.59], 'opening_visual_only_seconds':1,'voice_source_range':[427.37,471.59], 'voice_output_start':1, 'duration':45.22,'output':str(output.resolve()),
              'font':str(FONT),'cues':cues,'unresolved_cues':audit,'dings_seconds':[.8,2.8,20],
              'review_status':'preview_pending_ambiguous_speech_and_full_listening','auto_publish':False}
    (dest/'timeline.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    (dest/'captions.srt').write_text('\n\n'.join(f"{i+1}\n{stamp(c['start'])} --> {stamp(c['end'])}\n{c['text']}" for i,c in enumerate(cues))+'\n')
    header='[Script Info]\nScriptType: v4.00+\nPlayResX: 1440\nPlayResY: 2560\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n'
    header+=f'Style: Default,{font.getname()[0]},82,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,6,0,2,80,80,460,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
    (dest/'captions.ass').write_text(header+''.join(f"Dialogue: 0,{stamp(c['start'],True)},{stamp(c['end'],True)},Default,,0,0,0,,{c['text']}\n" for c in cues),encoding='utf-8')
    subprocess.run(['ffmpeg','-v','error','-hwaccel','none','-i',str(source),'-f','concat','-safe','0','-i',str(concat),'-i',str(ding),
        '-filter_complex_threads','1','-filter_complex',';'.join(chunks),'-map','[v]','-map','[a]', '-t',str(duration),'-r','30',
        '-c:v','libx264','-threads','2','-preset','veryfast','-crf','19','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart','-y',str(output)],check=True)
    print(str(output),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);run(parser.parse_args().root.resolve())
