import importlib.util
from pathlib import Path
p=Path(__file__).parents[1]/'scripts/recover_stable_unfinished_recordings.py'
s=importlib.util.spec_from_file_location('recover',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def test_only_finished_evidence_and_unclaimed_hd_sources():
    row=dict(end_time=None,local_deleted=0,transcribed=0,synced=0,clipped=0,start_time='2026-10-20T12:00:00')
    item=dict(status='valid_stable_unfinished',duration=110,width=1088,height=1920)
    assert m.measured_end(row,item)=='2026-10-20T12:01:50'
    for key,value in [('transcribed',1),('clipped',1),('synced',1),('local_deleted',1),('end_time','done')]:assert m.measured_end(row|{key:value},item) is None
    for change in [dict(status='probe_timeout_preserved'),dict(duration=0),dict(duration=float('nan')),dict(duration=2800),dict(width=720)]:assert m.measured_end(row,item|change) is None
