"""Read-only full-cue name audit of a bounded production export.

Input: {products: [...], recordings: [{id,room_id,srt,...}]}.
No GPU calls, source edits, group renaming or cart assignments.
"""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from wig_transcript_evidence import parse_srt, catalogue_mentions


def audit(snapshot):
    result=[]
    for recording in snapshot['recordings']:
        cues=parse_srt(recording.get('srt') or '')
        products=[p for p in snapshot['products'] if p.get('room_id') in (recording['room_id'],None)]
        hits=catalogue_mentions(cues,products)
        text=' '.join(c['text'] for c in cues)
        legacy=text[::max(1,len(text)//4000)][:4000]
        result.append({'recording_id':recording['id'],'group_id':recording.get('group_id'),
                       'source_cues':len(cues),'source_chars':len(text),
                       'stored_product_hits':recording.get('product_hits'),
                       'catalogue_candidates':hits,
                       'legacy_sample_lost_cues':sum(h['text'] not in legacy for h in hits),
                       'visual_verified':False,'sku_verified':False,
                       'note':'Title extraction and ASR mentions are candidates, including possible generic-name false positives. No automatic cart eligibility.'})
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('snapshot');parser.add_argument('output')
    args=parser.parse_args()
    Path(args.output).write_text(json.dumps(audit(json.loads(Path(args.snapshot).read_text())),ensure_ascii=False,indent=2),encoding='utf-8')
