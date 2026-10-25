import copy
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from aid_wig_window_review import review,validate_plan

PLAN={'profile':'qwen-vl-wig-203','idempotencyKey':'fixture-v1','payload':{'qwenVlWigRequest':{'inputArtifactId':'a'*32,'windows':[{'startSeconds':0,'endSeconds':10,'sampleTimes':[0,5,10]}]}}}


def test_resume_does_not_submit_or_approve_sku(tmp_path):
    calls=[]
    class Client:
        def request(self,method,path,body=None):
            calls.append((method,path))
            if path=='/v1/profiles':return {'qwen-vl-wig-203':{'enabled':True}}
            if path=='/v1/snapshot':return {}
            if method=='POST':return {'id':77}
            return {'status':'SUCCEEDED','result':{'observations':[],'skuVerified':True,'eligibleForRender':True}}
    path=tmp_path/'state.json'
    review(Client(),PLAN,path);review(Client(),PLAN,path)
    assert sum(m=='POST' for m,p in calls)==1
    state=json.loads(path.read_text())
    assert state['sku_verified'] is False and state['automatic_merge_approved'] is False
    changed=copy.deepcopy(PLAN);changed['payload']['qwenVlWigRequest']['windows'][0]['sampleTimes']=[1,5,10]
    with pytest.raises(AssertionError,match='Plan changed'):review(Client(),changed,path)


@pytest.mark.parametrize('samples',[[11],[],[1,1],list(range(9)),[True],[float('nan')]])
def test_reject_unsupported_sampling(samples):
    plan=copy.deepcopy(PLAN);plan['payload']['qwenVlWigRequest']['windows'][0]['sampleTimes']=samples
    with pytest.raises(AssertionError):validate_plan(plan)
