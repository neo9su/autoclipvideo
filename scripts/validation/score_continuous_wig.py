"""Compare the authorised 45259/900-1500s experiment to manual frame evidence.
These labels describe wearing states and visible appearance, never confirmed SKU.
They cannot establish correctness at unsampled instants or same-object rewear.
"""
import argparse
import json
from pathlib import Path


def expected(second):
    if not 900<=second<=1500:raise ValueError('Outside reviewed experiment interval')
    if second<987:return 'stable_wearing','A'
    if second<988:return 'transition',None
    if second<1010:return 'no_wig',None
    if second<1012:return 'transition',None
    if second<1271:return 'stable_wearing','B'
    if second<1272:return 'transition',None
    if second<1285:return 'no_wig',None
    if second<1286:return 'transition',None
    return 'stable_wearing','C'


def score(documents):
    rows=[];styles={}
    for doc in documents:
        if doc['state']!='complete':raise ValueError('Incomplete inference is not a scored result')
        for item in doc['response'].get('observations',[]):
            second=float(item['time_sec']);state,episode=expected(second)
            predicted=item.get('wear_state')
            if episode and predicted=='stable_wearing':styles.setdefault(episode,set()).add(item.get('style_signature'))
            rows.append({'time_sec':second,'expected_state':state,'expected_appearance_episode':episode,
                         'predicted_state':predicted,'signature':item.get('style_signature'),
                         'state_agrees':predicted==state,
                         'unworn_as_product':state=='no_wig' and predicted=='stable_wearing',
                         'transition_as_stable':state=='transition' and predicted=='stable_wearing',
                         'reason':item.get('reason'),'confidence':item.get('confidence')})
    return {'frame_count':len(rows),'exact_state_agreement':sum(r['state_agrees'] for r in rows),
            'unworn_as_product_count':sum(r['unworn_as_product'] for r in rows),
            'transition_as_stable_count':sum(r['transition_as_stable'] for r in rows),
            'signatures_by_sampled_episode':{k:sorted(str(v) for v in values) for k,values in styles.items()},
            'rows':rows,'visual_verified':False,'sku_verified':False,'same_object_rewear_verified':False,
            'limits':['One reviewed source sample; not production accuracy.',
                      'Reference states come from saved manual contact-sheet review.',
                      'A/B/C label visible appearance episodes, not catalogue products.',
                      'Sparse observations cannot prove continuous object identity or exclude unsampled transitions.']}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',action='append',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    result=score([json.loads(Path(path).read_text(encoding='utf-8')) for path in a.input])
    with Path(a.output).open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False))


if __name__=='__main__':main()
