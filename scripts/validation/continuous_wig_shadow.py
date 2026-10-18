"""One explicitly authorised shadow experiment; never writes production media/config."""
import argparse
import hashlib
import json
from pathlib import Path
import time
from urllib import request


def dump(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True);p.add_argument('--output',required=True)
    p.add_argument('--start',type=float,required=True);p.add_argument('--end',type=float,required=True)
    p.add_argument('--phase',required=True);p.add_argument('--times',required=True)
    a=p.parse_args()
    if not 0<a.end-a.start<=600:raise ValueError('One source interval must be at most 600 seconds')
    times=sorted(set(float(t) for t in a.times.split(',')))
    if not 1<=len(times)<=24 or any(t<a.start or t>a.end for t in times):raise ValueError('1-24 explicit times must stay inside the authorised source interval')
    if not a.phase.isidentifier():raise ValueError('Invalid phase name')
    root=Path(a.output);root.mkdir(parents=True,exist_ok=True)
    result_path=root/(a.phase+'.json')
    with result_path.open('x',encoding='utf-8') as f:json.dump({'state':'reserved','times':times},f)
    source=Path(a.source).resolve(strict=True);stat=source.stat()
    import cv2
    from PIL import Image,ImageDraw
    cap=cv2.VideoCapture(str(source));frames=[]
    sheet=Image.new('RGB',(6*130,((len(times)+5)//6)*250),'black');draw=ImageDraw.Draw(sheet)
    frame_dir=root/a.phase;frame_dir.mkdir()
    try:
        for i,t in enumerate(times):
            cap.set(cv2.CAP_PROP_POS_MSEC,t*1000);ok,bgr=cap.read()
            if not ok:raise ValueError('Cannot decode requested frame')
            im=Image.fromarray(cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB));im.thumbnail((448,448))
            path=frame_dir/f'{t:.3f}.jpg';im.save(path,quality=90)
            frames.append({'requested_sec':t,'decoded_next_sec':cap.get(cv2.CAP_PROP_POS_MSEC)/1000,
                           'file':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
            preview=im.copy();preview.thumbnail((130,230));x,y=i%6*130,i//6*250
            sheet.paste(preview,(x,y+20));draw.text((x+3,y+3),f'{t:.1f}s',fill='white')
    finally:cap.release()
    sheet.save(root/(a.phase+'-sheet.jpg'),quality=90)
    windows=[{'start_sec':chunk[0],'end_sec':chunk[-1]+0.01,'sample_times':chunk} for offset in range(0,len(times),8) if (chunk:=times[offset:offset+8])]
    payload={'video_path':str(source),'target_name':'','target_color':'','windows':windows}
    record={'state':'in_progress','source_path':str(source),'source_size':stat.st_size,'source_mtime_ns':stat.st_mtime_ns,
            'scope_start_sec':a.start,'scope_end_sec':a.end,'frames':frames,'request':payload,
            'visual_verified':False,'production_config_changed':False,'production_media_modified':False}
    dump(result_path,record)
    started=time.monotonic()
    try:
        req=request.Request('http://127.0.0.1:8897/analyze-wig-windows',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
        with request.urlopen(req,timeout=300) as response:result=json.load(response)
        after=source.stat()
        if (stat.st_size,stat.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('Source changed during test')
        record.update(state='complete',response=result,elapsed_seconds=round(time.monotonic()-started,2))
        dump(result_path,record)
        print(json.dumps({'phase':a.phase,'state':record['state'],'elapsed_seconds':record['elapsed_seconds'],'observations':result.get('observations',[])},ensure_ascii=False),flush=True)
    except BaseException as e:
        record.update(state='failed',error=type(e).__name__+': '+str(e),elapsed_seconds=round(time.monotonic()-started,2));dump(result_path,record);raise


if __name__=='__main__':main()
