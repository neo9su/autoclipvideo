"""Two tiny scheduler-only acceptance jobs for the cloned 203 renderer."""
from pathlib import Path
import hashlib,importlib.util,json,os,ssl,subprocess,time,urllib.parse,urllib.request
OUT=Path(__file__).parents[1]/'output/qianchuan203-profile-verification';PROFILE='qianchuan-render-203'
def save(state):
 p=OUT/'state.json';tmp=p.with_suffix('.writing');tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2));os.replace(tmp,p)
def main():
 OUT.mkdir(parents=True,exist_ok=True)
 spec=importlib.util.spec_from_file_location('aid_client','/Users/susunxin/.codex/skills/gpu-resource-scheduler/scripts/gpu_job.py');client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)
 profiles=client.request('GET','/v1/profiles');snapshot=client.request('GET','/v1/snapshot');profile=profiles[PROFILE]
 assert profile['enabled'] and profile['allowedNodeIds']==['gpu-203'] and profile['gpuIndices']==[0]
 source=OUT/'qianchuan203-scheduler-test.mp4'
 if not source.exists():subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=144x256:rate=30','-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','8','-c:v','libx264','-preset','ultrafast','-c:a','aac',str(source)],check=True,timeout=30)
 state=json.loads((OUT/'state.json').read_text()) if (OUT/'state.json').exists() else {'jobs':{},'profile':profile,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
 assert hashlib.sha256(source.read_bytes()).hexdigest()==state['source_sha256']
 base=os.environ['AID_GPU_MANAGER_URL'].rstrip('/');key=Path(os.environ['AID_GPU_MANAGER_API_KEY_FILE']).read_text().strip();ctx=ssl.create_default_context(cafile=os.environ['AID_GPU_MANAGER_CA_FILE'])
 if not state.get('artifact_id'):
  req=urllib.request.Request(base+'/v1/artifacts',data=source.read_bytes(),method='POST',headers={'Authorization':'Bearer '+key,'Content-Type':'application/octet-stream','X-File-Name':source.name})
  with urllib.request.urlopen(req,context=ctx,timeout=30) as h:artifact=json.load(h)
  state['artifact_id']=artifact['id'];save(state)
 aid=state['artifact_id']
 requests={
  'compose':dict(clips=[dict(inputArtifactId=aid,startSeconds=0,durationSeconds=3),dict(inputArtifactId=aid,startSeconds=4,durationSeconds=3)],aspectRatio='9:16',preserveAudio=True,maxDurationSeconds=6,outputFilename='qianchuan203-compose-validation-v1.mp4'),
  '2k':dict(clips=[dict(inputArtifactId=aid,startSeconds=1,durationSeconds=4)],aspectRatio='9:16',preserveAudio=True,maxDurationSeconds=4,outputFilename='qianchuan203-2k-validation-v1.mp4',renderMode='qianchuan_compliant_2k',assetId=hashlib.sha256(b'qianchuan203-2k-validation-v1').hexdigest()[:32])}
 for mode,payload in requests.items():
  item=state['jobs'].setdefault(mode,{})
  if not item.get('id'):
   request=dict(profile=PROFILE,idempotencyKey='douyin-qianchuan203-'+mode+'-acceptance-v1',payload={'qianchuanRenderRequest':payload});item['request']=request;save(state)
   job=client.request('POST','/v1/jobs',request);item.update(id=job['id'],status=job['status'],queuePosition=job.get('queuePosition'),estimatedStartSeconds=job.get('estimatedStartSeconds'),estimatedColdStartSeconds=job.get('estimatedColdStartSeconds'));save(state)
   print(json.dumps(dict(mode=mode,**{k:v for k,v in item.items() if k!='request'})),flush=True)
  for attempt in range(120):
   job=client.request('GET','/v1/jobs/'+str(item['id']));item.update(status=job['status'],assigned_gpu_ids=job.get('assigned_gpu_ids'),assigned_node_id=job.get('assigned_node_id'),error=job.get('error_message'));save(state)
   if job['status'] in {'SUCCEEDED','FAILED','LOST','CANCELLED'}:break
   time.sleep(5)
  assert job['status']=='SUCCEEDED',str(item)
  result=job['result'];result=json.loads(result) if isinstance(result,str) else result
  assert result['nodeId']=='gpu-203','Wrong execution node'
  item['result']=result;save(state)
  target=OUT/result['filename']
  if not target.exists():
   req=urllib.request.Request(base+'/v1/jobs/'+str(item['id'])+'/download',headers={'Authorization':'Bearer '+key})
   with urllib.request.urlopen(req,context=ctx,timeout=60) as h:raw=h.read()
   assert hashlib.sha256(raw).hexdigest()==result['sha256'],'Download hash mismatch';target.write_bytes(raw)
  probe=subprocess.run(['ffprobe','-v','error','-show_entries','stream=codec_type,codec_name,width,height:format=duration','-of','json',str(target)],check=True,capture_output=True,timeout=15);meta=json.loads(probe.stdout)
  video=next(x for x in meta['streams'] if x['codec_type']=='video');expected=(1440,2560) if mode=='2k' else (1080,1920)
  assert (video['width'],video['height'])==expected and video['codec_name']=='h264'
  assert any(x['codec_type']=='audio' for x in meta['streams'])
  assert abs(float(meta['format']['duration'])-(4 if mode=='2k' else 6))<.3
  item.update(verified=True,download_sha256=hashlib.sha256(target.read_bytes()).hexdigest());save(state);print(json.dumps({'mode':mode,'id':item['id'],'status':item['status'],'node':result['nodeId'],'video':meta}),flush=True)
 state['finished']=True;save(state)
if __name__=='__main__':main()
