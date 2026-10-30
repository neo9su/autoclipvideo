from pathlib import Path
import json,hashlib,datetime,sys,os,subprocess,time,urllib.request
r=Path.home()/'.config/aid-gpu-scheduler';name='latentsync-15-203'
values=dict(line.split('=',1) for line in (r/'manager.env').read_text().splitlines() if '=' in line and not line.startswith('#'));token=values['GPU_MANAGER_ADMIN_TOKEN'].strip().strip('"').strip("'")
def call(path,data=None,method='GET'):
 req=urllib.request.Request('http://127.0.0.1:18120'+path,data=json.dumps(data).encode() if data is not None else None,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},method=method)
 with urllib.request.urlopen(req,timeout=15) as h:return json.load(h)
snapshot=call('/v1/snapshot');assert not snapshot['running'],'Manager maintenance requires idle jobs'
p=r/'profiles.json';s=r/'services.json';pb=p.read_bytes();sb=s.read_bytes();profiles=json.loads(pb);services=json.loads(sb);assert name not in profiles
clients=[x for x in call('/v1/admin/client-keys')['items'] if x['source']=='douyin' and x['status']=='ACTIVE'];assert clients
profiles[name]={'displayName':'203 LatentSync 1.5 口型样片','gpuCount':1,'gpuIndices':[0],'allowedNodeIds':['gpu-203'],'enabled':True,'defaultPriority':50,'maxClientPriority':50,'exclusive':True,'nonPreemptible':True,'warmKey':None,'warmSeconds':0,'warmPriorityBoost':0,'switchPenaltySeconds':60,'expectedSeconds':600,'maxRunSeconds':3600,'minClientPriority':0}
entry=dict(next(x for x in services['services'] if x['profile']=='qianchuan-render'));entry.update(id='latentsync-15-203',name='203口型同步样片',profile=name,nodeId='gpu-203',currentState='CONFIGURED',adapterReady=True,controlName='LatentSync 1.5 fixed pilot adapter',notes='Independent 5-15 second pilot, input artifact plus bounded text. No production publishing.',recommendedAction='通过AID提交样片');services['services'].append(entry)
b=Path.home()/'.local/state/aid-gpu-scheduler/backups'/('latentsync-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));b.mkdir(mode=0o700)
(b/'profiles.before.json').write_bytes(pb);(b/'services.before.json').write_bytes(sb);(b/'clients.before.json').write_text(json.dumps([{'id':x['id'],'allowedProfiles':x['allowedProfiles']} for x in clients]))
assert p.read_bytes()==pb and s.read_bytes()==sb
for f,d in [(p,profiles),(s,services)]:
 t=f.with_suffix('.lipsync.tmp');t.write_text(json.dumps(d,ensure_ascii=False,indent=2));os.replace(t,f)
try:
 subprocess.run(['systemctl','--user','restart','gpu-resource-manager.service'],check=True)
 for i in range(20):
  try:call('/v1/snapshot');break
  except Exception:time.sleep(.5)
 for c in clients:call('/v1/admin/client-keys/'+str(c['id'])+'/profiles',{'allowedProfiles':sorted(set(c['allowedProfiles'])|{name}),'actor':'codex-lipsync-pilot'},'PATCH')
 print(json.dumps({'backup':str(b),'profile':name,'clients':[c['id'] for c in clients]}))
except Exception:
 for c in clients:
  try:call('/v1/admin/client-keys/'+str(c['id'])+'/profiles',{'allowedProfiles':c['allowedProfiles'],'actor':'codex-lipsync-rollback'},'PATCH')
  except Exception:pass
 p.write_bytes(pb);s.write_bytes(sb);subprocess.run(['systemctl','--user','restart','gpu-resource-manager.service'],check=True);raise
