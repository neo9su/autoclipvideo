"""Exercise the actual recorder class without importing unrelated network clients."""
import ast,asyncio,logging,os
from pathlib import Path
from typing import Optional
from datetime import datetime
import pytest
SOURCE=Path(__file__).parents[1]/'backend/recorder.py'

@pytest.mark.parametrize('duration',[None,float('nan'),float('inf'),0,-1])
def test_unavailable_probe_keeps_bytes_and_callbacks_idle(tmp_path,duration):
    tree=ast.parse(SOURCE.read_text())
    node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='RoomRecorder')
    async def probe(_):return duration
    def classify(d):return 'accepted' if d and d==d and 0<d<float('inf') else 'duration_unavailable'
    ns=dict(asyncio=asyncio,logging=logging,logger=logging.getLogger('test'),os=os,
            Optional=Optional,datetime=datetime,probe_duration=probe,classify_duration=classify)
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(SOURCE),'exec'),ns)
    events=[]
    async def callback(*args):events.append(args)
    recorder=ns['RoomRecorder'](1,'test','invalid',on_segment_done=callback,on_segment_rejected=callback)
    path=tmp_path/'source.mp4';path.write_bytes(b'original evidence')
    assert asyncio.run(recorder._finalize_segment(str(path),0)) is False
    assert path.read_bytes()==b'original evidence'
    assert events==[]
