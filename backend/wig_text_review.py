"""Bounded read-only bridge to optional isolated CPU phonetic runtime."""
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
from wig_transcript_evidence import parse_srt


def review_subtitles(raw, products, start, end, *, runtime=None):
    if not all(math.isfinite(t) for t in (start,end)) or start<0 or end<=start or end-start>600:
        raise ValueError('请输入有效源时间，单次最多600秒')
    cues=[c for c in parse_srt(raw.decode('utf-8-sig')) if start<=c['start_sec'] and c['end_sec']<=end]
    if len(cues)>1000 or len(products)>5000:raise ValueError('单次复核内容过多，请缩小时间范围')
    root=Path(runtime) if runtime else Path(__file__).resolve().parents[1]/'text-review-runtime'
    worker=root/'worker.py'
    if not worker.is_file():raise ValueError('同音复核运行组件尚未安装')
    data=json.dumps({'cues':cues,'products':products},ensure_ascii=False).encode('utf-8')
    if len(data)>2*1024*1024:raise ValueError('单次复核内容过多，请缩小时间范围')
    try:
        completed=subprocess.run([sys.executable,'-I','-X','utf8',str(worker)],input=data,
                                 capture_output=True,timeout=30,check=True)
        hits=json.loads(completed.stdout)['candidates']
    except (subprocess.SubprocessError,ValueError,KeyError) as exc:
        raise ValueError('同音复核未完成，原始字幕未修改') from exc
    by_id={p['id']:p for p in products}
    for hit in hits:
        hit['product_candidates']=[{'id':i,'product_name':by_id[i].get('product_name'),
                                    'product_url':by_id[i].get('product_url')}
                                   for i in hit['catalogue_ids']]
    return {'start_sec':start,'end_sec':end,'subtitle_sha256':hashlib.sha256(raw).hexdigest(),
            'catalogue_sha256':hashlib.sha256(json.dumps(products,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
            'candidate_count':len(hits),'candidates':hits[:500],'truncated':len(hits)>500,
            'read_only':True,'visual_verified':False,'sku_verified':False,'eligible_for_render':False}
