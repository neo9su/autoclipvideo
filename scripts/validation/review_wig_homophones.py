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


def retrieve(cues, products, *, converter=None):
    if converter is None:
        from pypinyin import lazy_pinyin
        converter=lazy_pinyin
    names={}
    for product in products:
        name=hairstyle_name(product.get('product_name'))
        if name:names.setdefault(name, []).append(product['id'])
    aliases=[]
    for name,ids in names.items():
        for alias in re.split('[&＆]',name):
            # Short/generic syllables produce too many unrelated matches.
            if len(alias)>=3 and re.fullmatch(r'[\u4e00-\u9fff]+',alias):
                aliases.append((alias,tuple(converter(alias)),name,ids))
    hits=[]
    for cue in cues:
        text=cue['text']
        # Do not join separated phrases or punctuation into invented names.
        for match in re.finditer(r'[\u4e00-\u9fff]+',text):
            phrase=match.group();syllables=tuple(converter(phrase))
            if len(syllables)!=len(phrase):continue
            for alias,wanted,name,ids in aliases:
                for i in range(len(phrase)-len(alias)+1):
                    observed=phrase[i:i+len(alias)]
                    if observed!=alias and syllables[i:i+len(alias)]==wanted:
                        hits.append({'start_sec':cue['start_sec'],'end_sec':cue['end_sec'],
                                     'original_text':text,'observed_text':observed,'candidate_alias':alias,
                                     'hairstyle_name':name,'catalogue_ids':ids,
                                     'evidence':'same_toneless_pinyin_not_verified_audio',
                                     'current_assertion':False,'visual_verified':False,'sku_verified':False,
                                     'review_required':True})
    return hits


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
