"""Compare independent sampled observations; agreement never proves SKU identity."""
import math
from collections import defaultdict


def reconcile(runs):
    artifacts={r['input_artifact_id'] for r in runs}
    if len(artifacts)!=1 or not next(iter(artifacts)):
        raise ValueError('All observations must refer to the same source artifact')
    jobs=[r['job_id'] for r in runs]
    if len(jobs)!=len(set(jobs)):
        raise ValueError('Duplicate jobs cannot count as independent observations')
    points=defaultdict(list)
    for run in runs:
        seen=set()
        for row in run['observations']:
            t=row.get('time_sec')
            if isinstance(t,bool) or not isinstance(t,(int,float)) or not math.isfinite(t) or t<0:
                raise ValueError('Invalid source timestamp')
            if t in seen:raise ValueError('Duplicate timestamp within one job')
            seen.add(t)
            points[t].append({'job_id':run['job_id'],**row})
    result=[]
    for t,rows in sorted(points.items()):
        states={r.get('wear_state') for r in rows}
        signatures={tuple(part for part in str(r.get('style_signature') or '').split('|') if part and part!='未知') for r in rows}
        reasons=[]
        if len(states)>1:reasons.append('wear_state_disagreement')
        if len(signatures)>1:reasons.append('appearance_disagreement')
        if len(rows)<2:reasons.append('single_observation_only')
        if any(r.get('wear_state')!='stable_wearing' for r in rows):reasons.append('not_consistently_wearing')
        if any(not r.get('style_signature') or '未知' in r['style_signature'] for r in rows):reasons.append('incomplete_visual_features')
        result.append({'time_sec':t,'observations':rows,'issues':reasons,
                       'status':'conflict' if len(states)>1 or len(signatures)>1 else 'review_required',
                       'visual_verified':False,'sku_verified':False})
    return {'source_artifact_id':next(iter(artifacts)),'jobs':jobs,'points':result,
            'conflicting_timestamps':sum(p['status']=='conflict' for p in result),
            'automatic_merge_approved':False,'eligible_for_render':False,
            'scope':'sampled observations, not continuous wearing verification'}
