"""Isolated, resumable AID render preview; never changes production records."""
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import ssl
import time
import urllib.parse
from aid_transcribe_recording import save

BATCH = Path(r'C:\Users\neo\douyin_backend\codex_operations\production-20261025')


def run():
    config = json.loads(Path(r'C:\ProgramData\AIDGPU\douyin-client\environment-render.json').read_text())
    os.environ.update(config)
    spec = importlib.util.spec_from_file_location('aid', BATCH / 'aid_gpu_client.py')
    client = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(client)
    assert client.request('GET', '/v1/profiles')['qianchuan-render']['enabled']
    client.request('GET', '/v1/snapshot')
    source_state = json.loads((BATCH / 'recording-45409.json').read_text())
    source = Path(source_state['source'])
    timeline = {'recording_id':45409, 'source_sha256':source_state['source_sha256'],
                'startSeconds':427.37, 'durationSeconds':45.64,
                'name':'棕色_齐刘海_长直发_半扎演示', 'product_id':None,
                'review_status':'preview_pending_full_playback', 'source_unchanged':True}
    asset_id = hashlib.sha256(json.dumps(timeline, sort_keys=True).encode()).hexdigest()[:32]
    state_path = BATCH / 'render-45409-v1.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {'timeline':timeline,'asset_id':asset_id}
    if not state.get('artifact_id'):
        url = urllib.parse.urlsplit(config['AID_GPU_MANAGER_URL'])
        ctx = ssl.create_default_context(cafile=config['AID_GPU_MANAGER_CA_FILE'])
        conn = http.client.HTTPSConnection(url.hostname,url.port,context=ctx,timeout=600)
        stat = source.stat()
        conn.putrequest('POST',url.path.rstrip('/')+'/v1/artifacts')
        conn.putheader('Authorization','Bearer '+Path(config['AID_GPU_MANAGER_API_KEY_FILE']).read_text().strip())
        conn.putheader('Content-Type','application/octet-stream')
        conn.putheader('Content-Length',str(stat.st_size))
        conn.putheader('X-File-Name',urllib.parse.quote(source.name))
        conn.endheaders()
        digest=hashlib.sha256()
        with source.open('rb') as f:
            for chunk in iter(lambda:f.read(1024*1024),b''):
                digest.update(chunk)
                conn.send(chunk)
        response=conn.getresponse()
        artifact=json.load(response)
        conn.close()
        assert response.status==201, f'Upload HTTP {response.status}'
        assert digest.hexdigest()==timeline['source_sha256'], 'Source hash changed'
        assert source.stat().st_mtime_ns==stat.st_mtime_ns, 'Source changed'
        state['artifact_id']=artifact['id']
        save(state_path,state)
    request={'profile':'qianchuan-render','idempotencyKey':'recording-45409-preview-'+asset_id,
             'payload':{'qianchuanRenderRequest':{
                 'clips':[{'inputArtifactId':state['artifact_id'],'startSeconds':427.37,'durationSeconds':45.64}],
                 'aspectRatio':'9:16','maxDurationSeconds':45.64,'preserveAudio':True,
                 'outputFilename':'recording-45409-brown-fringe-preview-v1.mp4',
                 'renderMode':'qianchuan_compliant_2k','assetId':asset_id}}}
    save(BATCH/'render-request-45409-v1.json',request)
    if not state.get('job_id'):
        job=client.request('POST','/v1/jobs',request)
        state['job_id']=job['id']
        save(state_path,state)
    while True:
        job=client.request('GET','/v1/jobs/'+str(state['job_id']))
        state.update(status=job['status'],error=job.get('error_message'))
        if job['status'] in {'SUCCEEDED','FAILED','CANCELLED','LOST'}:
            state['result']=job.get('result')
            save(state_path,state)
            break
        save(state_path,state)
        time.sleep(10)


if __name__=='__main__':
    run()
