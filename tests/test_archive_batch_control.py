import threading
import time
import pytest
from scripts.archive_clip_temps_scp_batch import run_batch


def test_two_transfer_bound_and_all_results():
    lock=threading.Lock();active=maximum=0
    def operation(plan):
        nonlocal active,maximum
        with lock:active+=1;maximum=max(maximum,active)
        time.sleep(.01)
        with lock:active-=1
        return {'job_id':plan['job_id']}
    results,errors=run_batch([{'job_id':str(i)} for i in range(6)],operation,2)
    assert len(results)==6 and not errors and maximum==2


def test_failure_stops_unstarted_work():
    called=[]
    def operation(plan):
        called.append(plan['job_id']);raise RuntimeError('fixture failure')
    results,errors=run_batch([{'job_id':str(i)} for i in range(5)],operation,1)
    assert called==['0'] and len(errors)==1 and not results
    with pytest.raises(ValueError):run_batch([],operation,3)
