"""CPU-only, tone-insensitive catalogue retrieval; never rewrite subtitles or name clips."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from wig_catalog_names import hairstyle_name
from wig_transcript_evidence import parse_srt


from wig_homophone_review import retrieve


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--srt',type=Path,required=True);p.add_argument('--catalogue',type=Path,required=True)
    p.add_argument('--start',type=float,required=True);p.add_argument('--end',type=float,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    import math
    if not all(math.isfinite(t) for t in (a.start,a.end)) or a.start<0 or a.end<=a.start:p.error('Invalid scope')
    raw=a.srt.read_bytes();catalogue=a.catalogue.read_bytes()
    cues=[c for c in parse_srt(raw.decode('utf-8-sig')) if a.start<=c['start_sec'] and c['end_sec']<=a.end]
    hits=retrieve(cues,json.loads(catalogue))
    import importlib.metadata
    result={'version':'wig-homophone-review-v1','pypinyin_version':importlib.metadata.version('pypinyin'),
            'subtitle_sha256':hashlib.sha256(raw).hexdigest(),'catalogue_sha256':hashlib.sha256(catalogue).hexdigest(),
            'scope_sec':[a.start,a.end],'candidates':hits,'eligible_for_render':False,
            'production_modified':False,'gpu_calls':0}
    with a.output.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({'candidates':len(hits),'names':sorted({h['hairstyle_name'] for h in hits})},ensure_ascii=False))
