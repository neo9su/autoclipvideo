"""Authorised isolated Qwen3.5 comparison; no production service/DB writes."""
import argparse
import gc
import hashlib
import json
from pathlib import Path
import time
from urllib import request

SEQUENCE_PROMPT = '''这些帧来自同一主播的一段连续假发展示。按真实源时间分析可见动作，不把梳理、触摸、扎发当成摘戴。识别实际主播，不识别手机屏幕人物。手中拿着的假发与头上戴着的分开。脱下后露出的底发/发网不代表另一款商品，不能仅以黑色判断有无假发；只凭头发覆盖头部也不能确认戴了假发。证据不足写uncertain。不要猜商品名或SKU。
只返回JSON对象：{"frames":[{"time_sec":源时间,"state":"wearing/no_wig/hair_net/putting_on/taking_off/holding_only/occluded/uncertain之一","head_visible":true,"detached_wig_visible":false,"hair_arrangement":"loose/tied/braided/unknown之一","color":"可见颜色或unknown","bangs":"可见刘海或unknown","length":"发尾可见才记录长度，否则unknown","reason":"可见证据"}],"events":[{"start_sec":源时间,"end_sec":源时间,"action":"仅有相邻帧证据支持的动作"}]}。不把相似外观当成实物同一。'''


def dump(path,data):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)


def parse(raw):
    decoder=json.JSONDecoder()
    for i,ch in enumerate(raw):
        if ch in '[{':
            try:return decoder.raw_decode(raw[i:])[0]
            except ValueError:pass
    return None


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model',required=True);p.add_argument('--source',required=True)
    p.add_argument('--legacy-prompt',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();root=Path(a.output);root.mkdir(parents=True,exist_ok=False)
    status=root/'status.json'
    result={'state':'starting','model':a.model,'production_config_changed':False,'production_media_modified':False,'cases':[]}
    dump(status,result)
    from download_pinned_vision_model import verify
    manifest=json.loads((Path(a.model)/'source_manifest.json').read_text(encoding='utf-8'))
    if manifest['model']!='Qwen/Qwen3.5-4B' or manifest['revision']!='851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a':raise ValueError('Unexpected model revision')
    for item in manifest['files']:verify(Path(a.model)/item['name'],item)
    result['model_revision']=manifest['revision']
    import importlib.metadata
    result['runtime_versions']={n:importlib.metadata.version(n) for n in ('torch','transformers')}
    import torch
    import cv2
    from PIL import Image
    from transformers import AutoProcessor,AutoModelForMultimodalLM
    health=json.load(request.urlopen('http://127.0.0.1:8897/health',timeout=8))
    if health.get('loaded') or torch.cuda.mem_get_info()[0]<12500*1024**2:
        result.update(state='blocked',reason='Existing GPU workload or insufficient free memory');dump(status,result);return
    source=Path(a.source);before=source.stat();model=processor=None
    torch.cuda.reset_peak_memory_stats();started=time.monotonic()
    try:
        processor=AutoProcessor.from_pretrained(a.model,local_files_only=True,trust_remote_code=False)
        model=AutoModelForMultimodalLM.from_pretrained(a.model,local_files_only=True,trust_remote_code=False,dtype=torch.bfloat16,device_map='cuda',attn_implementation='sdpa').eval()
        result.update(state='running',load_seconds=round(time.monotonic()-started,2),gpu_name=torch.cuda.get_device_name())
        dump(status,result)
        legacy=Path(a.legacy_prompt).read_text(encoding='utf-8')
        cases=[('baseline_990',[990],legacy,448),('baseline_1170',[1170],legacy,448),('baseline_1320',[1320],legacy,448),
               ('remove_a',[985,987,988,990],SEQUENCE_PROMPT,768),
               ('put_b',[1009,1010,1011,1012],SEQUENCE_PROMPT,768),
               ('remove_b',[1269,1270,1271,1272],SEQUENCE_PROMPT,768),
               ('put_c',[1284,1285,1286,1287],SEQUENCE_PROMPT,768)]
        cap=cv2.VideoCapture(str(source))
        try:
            for case_index,(name,times,prompt,edge) in enumerate(cases):
                case_started=time.monotonic();content=[];frames=[];folder=root/name;folder.mkdir()
                for t in times:
                    cap.set(cv2.CAP_PROP_POS_MSEC,t*1000);ok,bgr=cap.read()
                    if not ok:raise RuntimeError('Frame unavailable: '+str(t))
                    im=Image.fromarray(cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB));im.thumbnail((edge,edge))
                    im.save(folder/f'{t}.jpg',quality=95)
                    meta={'window_index':case_index,'time_sec':float(t)}
                    frames.append({**meta,'pixel_sha256':hashlib.sha256(im.tobytes()).hexdigest(),'width':im.width,'height':im.height})
                    content.extend([{'type':'text','text':'frame='+json.dumps(meta)},{'type':'image','image':im}])
                content.append({'type':'text','text':prompt})
                inputs=processor.apply_chat_template([{'role':'user','content':content}],add_generation_prompt=True,tokenize=True,return_dict=True,return_tensors='pt',enable_thinking=False).to(model.device)
                with torch.inference_mode():tokens=model.generate(**inputs,max_new_tokens=256 if name.startswith('baseline') else 768,do_sample=False)
                raw=processor.decode(tokens[0][inputs['input_ids'].shape[-1]:],skip_special_tokens=True)
                case={'name':name,'times':times,'image_edge':edge,'frames':frames,'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'raw':raw,'parsed':parse(raw),'elapsed_seconds':round(time.monotonic()-case_started,2)}
                dump(folder/'result.json',case);result['cases'].append(case)
                result.update(peak_allocated_mib=round(torch.cuda.max_memory_allocated()/1024**2),peak_reserved_mib=round(torch.cuda.max_memory_reserved()/1024**2));dump(status,result)
                print(json.dumps({'case':name,'elapsed_seconds':case['elapsed_seconds'],'parsed':case['parsed']},ensure_ascii=False),flush=True)
                del inputs,tokens
        finally:cap.release()
        after=source.stat()
        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise RuntimeError('Source changed')
        result.update(state='complete',elapsed_seconds=round(time.monotonic()-started,2))
    except BaseException as e:
        result.update(state='failed',error=type(e).__name__+': '+str(e));raise
    finally:
        model=processor=None;gc.collect();torch.cuda.empty_cache()
        result['process_model_released']=True;dump(status,result)


if __name__=='__main__':main()
