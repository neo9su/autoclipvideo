import importlib.util
from pathlib import Path
import sqlite3

import pytest

spec = importlib.util.spec_from_file_location('activation', Path(__file__).parents[1] / 'scripts/activate_remote_audio.py')
activation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(activation)


@pytest.fixture
def idle(tmp_path, monkeypatch):
    path = tmp_path / 'jobs.db'
    connect = sqlite3.connect
    with connect(path) as db:
        for table in ['jobs', 'clip_jobs', 'tts_jobs', 'concat_jobs']:
            db.execute(f'create table {table}(status text)')
            db.execute(f"insert into {table} values ('done')")
    health = dict(pid=123, gpu_busy=False, queue_depth=0, clip_jobs_running=0,
                  clip_jobs_pending=0, concat_jobs_active=0, classic_concat_jobs_active=0)
    def request(port, route, **kwargs):
        return health if route == '/health' else {'status': 'done'}
    monkeypatch.setattr(activation, 'request', request)
    monkeypatch.setattr(activation.sqlite3, 'connect', lambda _: connect(path))
    return health, connect, path


def test_idle_worker_passes_without_any_mutation(idle):
    assert activation.assert_worker_idle({'dir_test'})['pid'] == 123


def test_legacy_false_idle_does_not_override_new_media_activity(idle):
    health, _, _ = idle
    health['media_jobs_active'] = {'director': 1}
    with pytest.raises(RuntimeError, match='complete media'):
        activation.assert_worker_idle(set())


def test_active_persisted_tts_prevents_restart(idle):
    _, connect, path = idle
    with connect(path) as db:
        db.execute("insert into tts_jobs values ('processing')")
    with pytest.raises(RuntimeError, match='tts_jobs'):
        activation.assert_worker_idle(set())


def test_active_director_prevents_restart(idle, monkeypatch):
    original = activation.request
    monkeypatch.setattr(activation, 'request', lambda port, path, **kw:
                        {'status': 'processing'} if '/director-jobs/' in path else original(port, path, **kw))
    with pytest.raises(RuntimeError, match='Director task'):
        activation.assert_worker_idle({'dir_test'})


def test_backend_only_activation_does_not_restart_gpu(tmp_path,monkeypatch):
    root=tmp_path/'backend';root.mkdir();(root/'codex_rollbacks').mkdir()
    with sqlite3.connect(root/'douyin.db') as db:
        db.execute('create table clip_groups(id,director_status,creative_status,qianchuan_status,classic_status)')
    health={'pid':42,'media_jobs_active':{}}
    calls=[];maintenance={'value':False}
    def request(port,path,method='GET',**kwargs):
        calls.append((port,path,method))
        if path=='/api/gpu/status':return {'maintenance':maintenance['value']}
        if path=='/api/gpu/maintenance':maintenance['value']=method=='POST';return {}
        if path=='/openapi.json':return {
            'paths':{'/audio-concat-jobs':{'post':{'requestBody':{'content':{'multipart/form-data':{'schema':{'$ref':'#/components/schemas/Body'}}}}}}},
            'components':{'schemas':{'Body':{'properties':{'speed_ratio':{'minimum':0.5,'maximum':2.0}}}}}}
        assert path=='/health', 'No GPU restart or workload submission permitted'
        return health
    def run(args,**kwargs):
        if args[:2]==['schtasks','/Run']:maintenance['value']=False
        return None
    monkeypatch.setattr(activation,'backend_task_plan',lambda: {'tasks':[{'name':'DouyinBackend8899SusunInteractive','enabled':True,'running':True},{'name':'Uvicorn8899','enabled':True,'running':False},{'name':'Wd8899Sys','enabled':True,'running':False}], 'restart_task':'DouyinBackend8899SusunInteractive'})
    monkeypatch.setattr(activation,'ROOT',root)
    monkeypatch.setattr(activation,'request',request)
    listeners=iter([{123},{123},set()])
    monkeypatch.setattr(activation,'backend_pids',lambda:next(listeners))
    monkeypatch.setattr(activation,'director_ids',lambda:set())
    monkeypatch.setattr(activation,'assert_worker_idle',lambda ids:health)
    monkeypatch.setattr(activation,'wait_health',lambda *args,**kwargs:health)
    monkeypatch.setattr(activation.subprocess,'run',run)
    activation.main(expected={},rollback_order=['fixture'],label='test',restart_worker=False)
    assert all(path!='/restart/gpu' for _,path,_ in calls)
    import json
    journal=json.loads(next((root/'codex_rollbacks').glob('*/activation.json')).read_text())
    compile(next((root/'codex_rollbacks').glob('*/restore_tasks.py')).read_text(), '<recovery>', 'exec')
    assert journal['backend_task_plan']['restart_task']=='DouyinBackend8899SusunInteractive'
    assert journal['phase']=='complete' and journal['gpu_pid_before']==journal['gpu_pid_after']==42


def test_maintenance_stops_supervisor_and_restores_original_owner(monkeypatch):
    plan={'tasks':[
        {'name':'Uvicorn8899','enabled':True,'running':False},
        {'name':'DouyinBackend8899SusunInteractive','enabled':True,'running':True},
        {'name':'DouyinBackend8899System','enabled':False,'running':False},
        {'name':'Wd8899Sys','enabled':True,'running':False}],
        'restart_task':'DouyinBackend8899SusunInteractive'}
    calls=[]
    monkeypatch.setattr(activation,'task_action',lambda action,name:calls.append((action,name)))
    monkeypatch.setattr(activation,'wait_health',lambda port:calls.append(('healthy',port)))
    changed=[]
    activation.pause_backend_tasks(plan,changed)
    assert calls==[('Disable','Uvicorn8899'),('Disable','DouyinBackend8899SusunInteractive'),
                   ('Disable','Wd8899Sys'),('End','DouyinBackend8899SusunInteractive')]
    activation.restore_backend_tasks(plan,changed)
    assert calls[-5:]==[('Enable','Uvicorn8899'),('Enable','DouyinBackend8899SusunInteractive'),
                        ('Run','DouyinBackend8899SusunInteractive'),('healthy',8899),('Enable','Wd8899Sys')]
    assert all(name!='DouyinBackend8899System' for _,name in calls)


@pytest.mark.parametrize('owners',[[],['Uvicorn8899','DouyinBackend8899SusunInteractive']])
def test_ambiguous_owner_fails_before_mutations(monkeypatch,owners):
    import json
    from types import SimpleNamespace
    tasks=[{'name':name,'enabled':True,'running':name in owners}
           for name in ['Uvicorn8899','Wd8899Sys','DouyinBackend8899SusunInteractive']]
    calls=[]
    def run(args,**kwargs):
        calls.append(args)
        return SimpleNamespace(stdout=json.dumps(tasks).encode())
    monkeypatch.setattr(activation.subprocess,'run',run)
    with pytest.raises(RuntimeError,match='exactly one running backend owner'):
        activation.backend_task_plan()
    assert len(calls)==1 and calls[0][0]=='powershell'


def test_guard_not_reenabled_before_backend_is_ready(monkeypatch):
    calls=[]
    monkeypatch.setattr(activation,'task_action',lambda action,name:calls.append((action,name)))
    def failed(_):raise RuntimeError('not ready')
    monkeypatch.setattr(activation,'wait_health',failed)
    with pytest.raises(RuntimeError,match='not ready'):
        activation.restore_backend_tasks({'restart_task':'Uvicorn8899'},['Uvicorn8899','Wd8899Sys'])
    assert ('Enable','Wd8899Sys') not in calls
