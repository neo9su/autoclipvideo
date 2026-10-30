import importlib.util,json,sys,time
from pathlib import Path
import pytest
ROOT=Path(__file__).parents[1]
p=ROOT/'integrations/aid/build_qianchuan_203.py';s=importlib.util.spec_from_file_location('port',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
BASE=Path('/Users/work/1-codex/aid-studio/deploy/local/gpu_qianchuan_render_worker.py')

def load():
 if not BASE.is_file():pytest.skip('Authoritative base renderer not available')
 ns={'__name__':'clone_test'};exec(m.worker(BASE.read_text()),ns);return ns

def test_profile_copy_is_pinned_and_original_unchanged():
 old=dict(displayName='base',allowedNodeIds=['gpu-222'],gpuIndices=[0,1],enabled=True,defaultPriority=60,maxRunSeconds=3600)
 new=m.profile(old);assert old['allowedNodeIds']==['gpu-222'];assert new['allowedNodeIds']==['gpu-203'];assert new['gpuIndices']==[0];assert new['defaultPriority']==60

def test_port_accepts_only_203_profile_and_retains_modes(tmp_path):
 ns=load();video=tmp_path/'v.mp4';video.touch()
 job=dict(profile=m.PROFILE,artifacts={'a'*32:str(video)},payload={'qianchuanRenderRequest':dict(clips=[dict(inputArtifactId='a'*32,durationSeconds=6)],renderMode='qianchuan_compliant_2k',assetId='b'*32)})
 req=ns['validated_request'](job);cmd=ns['compliant_render_command'](req,tmp_path/'out.mp4');assert cmd[0]==m.FFMPEG;assert '1440:2560' in ' '.join(cmd)
 job['profile']='qianchuan-render'
 with pytest.raises(RuntimeError):ns['load_job'](tmp_path/'missing')

def test_owned_process_timeout_works_without_unix_signals(tmp_path):
 ns=load();cancel=tmp_path/'cancel';cancel.write_text('cancel')
 with pytest.raises(RuntimeError,match='cancelled'):
  ns['run']([sys.executable,'-c','import time;time.sleep(20)'],cancel,time.monotonic()+5)

def test_no_cross_node_or_unix_group_kill_remains():
 ns=load();source=m.worker(BASE.read_text());assert 'gpu-222' not in source;assert 'os.killpg' not in source;assert m.agent_profile()['resultRequired'] is True
