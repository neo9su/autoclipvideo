"""Run from a saved manager backup, with explicit admin authorization."""
from pathlib import Path
import json,hashlib,os,subprocess,urllib.request
B=Path(__file__).parent;M=json.loads((B/'manifest.json').read_text());root=Path(M['profiles']).parent
values={}
for line in (root/'manager.env').read_text().splitlines():
 if '=' in line and not line.startswith('#'):
  k,v=line.split('=',1);values[k]=v.strip().strip('"').strip("'")
def call(path,body=None,method='GET'):
 req=urllib.request.Request('http://127.0.0.1:18120'+path,data=json.dumps(body).encode() if body is not None else None,method=method,headers={'Authorization':'Bearer '+values['GPU_MANAGER_ADMIN_TOKEN'],'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=10) as h:return json.load(h)
snapshot=call('/v1/snapshot');assert not any(j['profile']==M['profile'] for j in snapshot['running']+snapshot['queued']),'New profile still has tasks'
for key in ['profiles','services']:assert hashlib.sha256(Path(M[key]).read_bytes()).hexdigest()==M[key+'_after'],'Configuration drift'
old=json.loads((B/'clients.before.json').read_text());current={r['id']:r for r in call('/v1/admin/client-keys')['items']}
for row in old:assert set(current[row['id']]['allowedProfiles']) in [set(row['allowedProfiles']),set(row['allowedProfiles'])|{M['profile']}],'Credential scope drift'
for row in old:call('/v1/admin/client-keys/'+str(row['id'])+'/profiles',{'allowedProfiles':row['allowedProfiles'],'actor':'codex-qianchuan-203-rollback'},'PATCH')
for key in ['profiles','services']:
 data=(B/(key+'.before.json')).read_bytes();assert hashlib.sha256(data).hexdigest()==M[key+'_before'];p=Path(M[key]);t=p.with_name(p.name+'.rollback-tmp');t.write_bytes(data);os.replace(t,p)
subprocess.run(['systemctl','--user','restart','gpu-resource-manager.service'],check=True)
print('New manager profile and douyin scope additions reverted. Use the separate 203 node backup to remove its idle worker/config entry; source videos and existing jobs retained.')
