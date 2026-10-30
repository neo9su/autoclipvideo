import importlib.util
import json
from pathlib import Path
import sys
import types

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
import aid_recording_prerequisites_batch as worker


def test_preflight_preserves_low_resolution_and_resumes_without_resubmit(tmp_path,monkeypatch):
    monkeypatch.setattr(worker,'BATCH',tmp_path)
    paths={}
    for id in (1,2):
        paths[str(id)]=tmp_path/f'{id}.mp4';paths[str(id)].write_bytes(b'original')
    monkeypatch.setitem(sys.modules,'recording_paths',types.SimpleNamespace(resolve_recording_path=lambda filename:str(paths[filename])))
    (tmp_path/'inventory.json').write_text(json.dumps({'recordings':[{'id':i,'filename':str(i),'transcribed':0} for i in (1,2)]}))
    def probe(args,**kw):
        width=720 if args[-1].endswith('1.mp4') else 1080
        return types.SimpleNamespace(returncode=0,stdout=json.dumps({'streams':[{'codec_type':'video','width':width,'height':1920}],'format':{'duration':60}}))
    monkeypatch.setattr(worker.subprocess,'run',probe)
    calls=[]
    def run(id,batch):
        calls.append(id);(batch/f'recording-{id}.json').write_text(json.dumps({'phase':'TRANSCRIBED_NOT_CLIPPED','job_id':100+id}))
    monkeypatch.setattr(worker,'run',run)
    worker.main(limit=1);worker.main(limit=1)
    state=json.loads((tmp_path/'prerequisites-batch.json').read_text())
    assert calls==[2]
    assert state['completed_transcripts']==1
    assert state['items'][0]['reason']=='below_1080p_preserved'
    assert all(p.read_bytes()==b'original' for p in paths.values())


def test_pause_prevents_submission(tmp_path,monkeypatch):
    monkeypatch.setattr(worker,'BATCH',tmp_path)
    monkeypatch.setitem(sys.modules,'recording_paths',types.SimpleNamespace(resolve_recording_path=lambda _:None))
    (tmp_path/'inventory.json').write_text(json.dumps({'recordings':[{'id':1,'filename':'one','transcribed':0}]}))
    (tmp_path/'PAUSE_PREREQUISITES').touch()
    monkeypatch.setattr(worker,'run',lambda *_: (_ for _ in ()).throw(AssertionError('must not submit')))
    worker.main()
    assert json.loads((tmp_path/'prerequisites-batch.json').read_text())['items']==[]
