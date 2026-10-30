"""Explicitly authorized AID manager administration; never exposes credentials."""
from pathlib import Path
import copy,datetime,hashlib,json,os,subprocess,time,urllib.request
ROOT=Path.home()/'.config/aid-gpu-scheduler';NAME='qianchuan-render-203'
def auth():
    values={}
    for line in (ROOT/'manager.env').read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            key,value=line.split('=',1);values[key]=value.strip().strip('"').strip("'")
    return values['GPU_MANAGER_ADMIN_TOKEN']
def call(path,body=None,method='GET'):
    request=urllib.request.Request('http://127.0.0.1:18120'+path,data=json.dumps(body).encode() if body is not None else None,method=method,headers={'Authorization':'Bearer '+auth(),'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=8) as h:return json.load(h)
def digest(data):return hashlib.sha256(data).hexdigest()
def atomic(path,data):
    tmp=path.with_name(path.name+'.q203-tmp');tmp.write_bytes(data);os.replace(tmp,path)
def restart():
    subprocess.run(['systemctl','--user','restart','gpu-resource-manager.service'],check=True,capture_output=True)
    for attempt in range(20):
        try:return call('/v1/snapshot')['profiles']
        except Exception:
            if attempt==19:raise
            time.sleep(.5)
def main():
    snapshot=call('/v1/snapshot')
    assert not any(x.get('profile')==NAME for x in snapshot['running']+snapshot['queued'])
    clients=[{k:r[k] for k in ['id','name','source','status','allowedProfiles']} for r in call('/v1/admin/client-keys')['items'] if r['source']=='douyin' and r['status']=='ACTIVE']
    assert {x['id'] for x in clients}=={29,30},'Douyin credential identity changed; inspect first'
    p=ROOT/'profiles.json';s=ROOT/'services.json';pb=p.read_bytes();sb=s.read_bytes();profiles=json.loads(pb);services=json.loads(sb)
    assert NAME not in profiles and not any(x['profile']==NAME for x in services['services'])
    clone=copy.deepcopy(snapshot['profiles']['qianchuan-render']);clone.update(displayName='千川视频分析与重混（203）',allowedNodeIds=['gpu-203'],gpuIndices=[0],enabled=True)
    profiles[NAME]=clone
    entry=copy.deepcopy(next(x for x in services['services'] if x['profile']=='qianchuan-render'))
    entry.update(id='qianchuan-video-stack-203',name='203千川NVENC固定渲染',profile=NAME,nodeId='gpu-203',currentState='CONFIGURED',controlName='Windows fixed FFmpeg H.264 NVENC renderer',adapterReady=True,notes='复制现有千川拼接及单片段2K能力；固定203 GPU0；独立调度验收见部署记录',recommendedAction='经 qianchuan-render-203 调度到203；不回退到222')
    services['services'].append(entry)
    pa=json.dumps(profiles,ensure_ascii=False,indent=2).encode();sa=json.dumps(services,ensure_ascii=False,indent=2).encode()
    b=Path.home()/'.local/state/aid-gpu-scheduler/backups'/('qianchuan-203-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));b.mkdir(mode=0o700)
    (b/'profiles.before.json').write_bytes(pb);(b/'services.before.json').write_bytes(sb);(b/'clients.before.json').write_text(json.dumps(clients,ensure_ascii=False,indent=2))
    manifest=dict(profile=NAME,profiles=str(p),services=str(s),profiles_before=digest(pb),profiles_after=digest(pa),services_before=digest(sb),services_after=digest(sa),running_before=[{'id':x['id'],'profile':x['profile']} for x in snapshot['running']])
    (b/'manifest.json').write_text(json.dumps(manifest,indent=2));(b/'rollback.py').write_text(Path(__file__).with_name('rollback_qianchuan_203_manager.py').read_text())
    assert p.read_bytes()==pb and s.read_bytes()==sb,'Manager configuration changed concurrently'
    atomic(p,pa);atomic(s,sa)
    try:
        live=restart();assert live[NAME]['allowedNodeIds']==['gpu-203'];assert live['qianchuan-render']==snapshot['profiles']['qianchuan-render'],'Original profile changed'
        current={x['id']:x for x in call('/v1/admin/client-keys')['items']}
        for row in clients:
            assert set(current[row['id']]['allowedProfiles'])==set(row['allowedProfiles']),'Credential scope changed concurrently'
            scope=sorted(set(row['allowedProfiles'])|{NAME})
            call('/v1/admin/client-keys/'+str(row['id'])+'/profiles',{'allowedProfiles':scope,'actor':'codex-qianchuan-203-clone'},'PATCH')
        result=call('/v1/snapshot');result_clients={x['id']:x for x in call('/v1/admin/client-keys')['items']}
        assert all(NAME in result_clients[row['id']]['allowedProfiles'] for row in clients)
        output=dict(backup=str(b),profile=live[NAME],client_ids=[x['id'] for x in clients],existing_running_after=[{'id':x['id'],'profile':x['profile']} for x in result['running']])
        (b/'applied.json').write_text(json.dumps(output,ensure_ascii=False,indent=2));print(json.dumps(output,ensure_ascii=False))
    except BaseException:
        # Revert only our exact scope additions, preserving concurrent admin edits.
        latest={x['id']:x for x in call('/v1/admin/client-keys')['items']}
        for row in clients:
            current_scope=set(latest[row['id']]['allowedProfiles'])
            if current_scope==set(row['allowedProfiles'])|{NAME}:
                call('/v1/admin/client-keys/'+str(row['id'])+'/profiles',{'allowedProfiles':row['allowedProfiles'],'actor':'codex-qianchuan-203-auto-rollback'},'PATCH')
        atomic(p,pb);atomic(s,sb);restart();raise
if __name__=='__main__':main()
