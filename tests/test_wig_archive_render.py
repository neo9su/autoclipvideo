import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from wig_library_index import WigLibraryIndex
from wig_archive_render import ArchiveRenderer, sha256, write_json


def fixture(tmp_path,ready=True):
    storage=tmp_path/'media';storage.mkdir()
    source=storage/'source.mp4'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','color=red:s=160x90:r=10:d=4',
        '-f','lavfi','-i','color=blue:s=160x90:r=10:d=4','-f','lavfi','-i','sine=frequency=440:duration=8',
        '-filter_complex','[0:v][1:v]concat=n=2:v=1:a=0[v]','-map','[v]','-map','2:a',
        '-c:v','libx264','-g','80','-keyint_min','80','-sc_threshold','0','-threads','1','-c:a','aac',str(source)],check=True)
    index=WigLibraryIndex(storage/'_wig_library'/'index.sqlite')
    asset=index.register(source,8,1)
    segments=[{'start_sec':start,'end_sec':end,'hairstyle_name':name,'color':color,'features':[],
               'status':'ready' if ready else 'needs_evidence'} for start,end,name,color in [(1.3,2.7,'synthetic-red','red'),(4.3,5.7,'synthetic-blue','blue')]]
    plan=index.save_plan(asset,8,{'recording_id':8,'segments':segments},'synthetic-srt')
    return source,index,ArchiveRenderer(index,storage),plan['plan_id']


pytestmark=pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'),reason='ffmpeg/ffprobe required')


def test_precise_keyframe_cuts_manifest_idempotency_and_recovery(tmp_path):
    source,index,renderer,plan=fixture(tmp_path)
    before=sha256(source)
    job=renderer.export(plan)
    final=renderer.root/'exports'/job['batch_id']
    assert len(job['files'])==2 and sha256(source)==before
    for item in job['files']:
        output=final/item['relative_output']
        assert abs(item['video']['duration_seconds']-1.4)<0.15
        raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(output),'-vf','scale=1:1','-pix_fmt','rgb24','-f','rawvideo','-'])
        pixels=list(zip(raw[0::3],raw[1::3],raw[2::3]))
        if item['color']=='red': assert all(r>b+100 for r,g,b in pixels)
        else: assert all(b>r+100 for r,g,b in pixels)
    assert renderer.export(plan)['batch_id']==job['batch_id']
    renderer.batch_state(job['batch_id'],'withdraw')
    assert not final.exists() and source.exists()
    with pytest.raises(ValueError):renderer.export(plan)
    renderer.batch_state(job['batch_id'],'restore')
    assert final.exists() and sha256(source)==before
    manifest=json.loads((final/'source-manifest.json').read_text())
    assert manifest['source_sha256']==before
    assert manifest['time_basis']=='original_video_seconds'


def test_unverified_plan_or_changed_source_is_not_exported(tmp_path):
    source,index,renderer,plan=fixture(tmp_path,False)
    with pytest.raises(ValueError):renderer.export(plan)
    assert not (renderer.root/'exports').exists()
    with index.connect() as c:
        row=c.execute('SELECT document FROM plans WHERE plan_id=?',(plan,)).fetchone()
        document=json.loads(row['document'])
        for s in document['segments']:s['status']='ready'
        c.execute('UPDATE plans SET document=? WHERE plan_id=?',(json.dumps(document),plan))
    source.write_bytes(b'changed source')
    with pytest.raises(ValueError):renderer.export(plan)
    assert source.read_bytes()==b'changed source'
    assert not (renderer.root/'exports').exists()


def test_atomic_publish_before_journal_commit_is_recoverable(tmp_path):
    source,index,renderer,plan=fixture(tmp_path)
    job=renderer.export(plan)
    jp=renderer.root/'export_journals'/(job['batch_id']+'.json')
    job['state']='prepared';write_json(jp,job)
    recovered=renderer.batch_state(job['batch_id'],'recover')
    assert recovered['state']=='complete'
    output=renderer.root/'exports'/job['batch_id']/job['files'][0]['relative_output']
    output.write_bytes(b'damaged output')
    with pytest.raises(ValueError):renderer.export(plan)
    assert output.read_bytes()==b'damaged output'


def test_withdraw_interruption_is_retryable_and_pending_plan_api_rejects_export(tmp_path,monkeypatch):
    import asyncio
    import history_library_routes as routes
    from fastapi import HTTPException
    source,index,renderer,plan=fixture(tmp_path)
    job=renderer.export(plan)
    batch=job['batch_id'];jp=renderer.root/'export_journals'/(batch+'.json')
    job.update(state='withdrawing',previous_state='complete',origin='exports')
    write_json(jp,job)
    final=renderer.root/'exports'/batch
    trash=renderer.root/'recoverable_exports'/batch;trash.parent.mkdir(parents=True,exist_ok=True)
    final.rename(trash)
    assert renderer.batch_state(batch,'withdraw')['state']=='withdrawn'
    assert renderer.batch_state(batch,'withdraw')['state']=='withdrawn'
    assert renderer.batch_state(batch,'restore')['state']=='complete'
    assert renderer.batch_state(batch,'restore')['state']=='complete'
    index.set_state(plan,'withdrawn')
    monkeypatch.setattr(routes,'archive_renderer',lambda:renderer)
    with pytest.raises(HTTPException) as failure:asyncio.run(routes.create_archive_export(plan))
    assert failure.value.status_code==409
    assert len(renderer.list_batches())==1


def test_failed_cut_can_retry_without_overwriting_old_results(tmp_path,monkeypatch):
    import wig_archive_render
    source,index,renderer,plan=fixture(tmp_path)
    original=wig_archive_render.precise_cut
    def fail(*args):raise OSError('isolated transient failure')
    monkeypatch.setattr(wig_archive_render,'precise_cut',fail)
    with pytest.raises(OSError):renderer.export(plan)
    old=renderer.list_batches()[0]
    assert old['state']=='failed' and old['can_retry']
    monkeypatch.setattr(wig_archive_render,'precise_cut',original)
    job=renderer.batch_state(old['batch_id'],'retry')
    assert job['state']=='complete' and job['batch_id']==old['batch_id']
    assert len(list((renderer.root/'export_journals'/'attempts').glob('*.json')))==1
    assert len(list((renderer.root/'export_attempts').iterdir()))==1
