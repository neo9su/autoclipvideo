"""Resumable scheduler-only visual review; never infers SKU approval from model output."""
import hashlib
import json
import math
from pathlib import Path
import time


def validate_plan(plan):
    request=plan['payload']['qwenVlWigRequest']
    assert plan['profile']=='qwen-vl-wig-203'
    assert len(request['inputArtifactId'])==32 and all(c in '0123456789abcdef' for c in request['inputArtifactId'])
    assert set(request)<= {'inputArtifactId','targetName','targetColor','windows'}
    assert 1<=len(request['windows'])<=3
    for window in request['windows']:
        assert set(window)=={'startSeconds','endSeconds','sampleTimes'}
        start,end=window['startSeconds'],window['endSeconds']
        assert all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in (start,end))
        assert 0<=start<end<=86400
        samples=window['sampleTimes']
        assert isinstance(samples,list)
        assert all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in samples)
        assert 1<=len(samples)<=8 and len(set(samples))==len(samples)
        assert all(start<=point<=end for point in samples)
    return plan


def review(client,plan,state_path):
    validate_plan(plan)
    assert client.request('GET','/v1/profiles')['qwen-vl-wig-203']['enabled']
    client.request('GET','/v1/snapshot')
    state_path=Path(state_path)
    digest=hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()
    state=json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
    if state.get('request_sha256'):assert state['request_sha256']==digest,'Plan changed; do not reuse job'
    if not state.get('id'):
        state['id']=client.request('POST','/v1/jobs',plan)['id']
    state['request_sha256']=digest
    def save():
        temp=state_path.with_suffix('.writing');temp.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(state_path)
    save()
    while True:
        job=client.request('GET','/v1/jobs/'+str(state['id']))
        state.update(status=job['status'],error=job.get('error_message'))
        save()
        if job['status'] in {'SUCCEEDED','FAILED','CANCELLED','LOST'}:break
        time.sleep(10)
    if job['status']=='SUCCEEDED':
        result=job.get('result')
        if isinstance(result,str):result=json.loads(result)
        assert isinstance(result,dict) and isinstance(result.get('observations'),list)
        state.update(result=result,sku_verified=False,automatic_merge_approved=False,
                     scope='sampled visual observations; not continuous tracking validation')
        save()
    return state


if __name__=='__main__':
    import argparse,importlib.util
    parser=argparse.ArgumentParser();parser.add_argument('plan',type=Path);parser.add_argument('state',type=Path)
    parser.add_argument('--client',type=Path,required=True);args=parser.parse_args()
    spec=importlib.util.spec_from_file_location('aid',args.client);client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)
    result=review(client,json.loads(args.plan.read_text(encoding='utf-8')),args.state)
    print(json.dumps({'id':result['id'],'status':result['status'],'error':result.get('error')}))
