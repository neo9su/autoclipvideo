"""AID administrator use only, after explicit host/upgrade authorization.

No SSH, model/service restarts, or GPU workload execution. Check scheduler idle
state separately before applying. Default is a read-only inspection.
"""
from pathlib import Path
import argparse,hashlib,json,os,subprocess

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def atomic(path,data):
    tmp=path.with_name(path.name+'.legacy-update');tmp.write_bytes(data);os.replace(tmp,path)
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--worker',required=True,type=Path);parser.add_argument('--apply',action='store_true');parser.add_argument('--rollback',action='store_true');args=parser.parse_args()
    assert not(args.apply and args.rollback)
    bundle=Path(__file__).parent;m=json.loads((bundle/'manifest.json').read_text());worker=args.worker;module=worker.with_name('legacy_clip_worker.py')
    assert worker.name==m['worker_basename'],'Unexpected worker target'
    expected=m['after'] if args.rollback else m['before'];assert sha(worker)==expected,'Worker version drift'
    assert sha(bundle/'worker.before.py')==m['before'] and sha(bundle/'worker.after.py')==m['after']
    assert sha(bundle/'legacy_clip_worker.py')==m['module_sha']
    if args.rollback:
        assert module.is_file() and sha(module)==m['module_sha'],'Extension drift'
        atomic(worker,(bundle/'worker.before.py').read_bytes());module.unlink();print('Original fixed worker restored; services and task results untouched');return
    assert not module.exists(),'Extension already exists; inspect before upgrading'
    if not args.apply:print('Hashes verified; no changes. Explicit AID administration authorization and idle check required before --apply.');return
    filters=subprocess.run(['/usr/bin/ffmpeg','-hide_banner','-filters'],check=True,capture_output=True,text=True,timeout=15).stdout
    assert any(' subtitles ' in line for line in filters.splitlines()),'FFmpeg libass/subtitles filter missing; do not silently drop captions'
    encoders=subprocess.run(['/usr/bin/ffmpeg','-hide_banner','-encoders'],check=True,capture_output=True,text=True,timeout=15).stdout
    assert 'h264_nvenc' in encoders,'Fixed NVENC encoder unavailable'
    fonts=subprocess.run(['fc-list',':lang=zh'],check=True,capture_output=True,text=True,timeout=15).stdout
    assert fonts.strip(),'Chinese fonts unavailable; review dependencies first'
    compile((bundle/'worker.after.py').read_bytes(),str(worker),'exec');compile((bundle/'legacy_clip_worker.py').read_bytes(),str(module),'exec')
    atomic(module,(bundle/'legacy_clip_worker.py').read_bytes())
    try:atomic(worker,(bundle/'worker.after.py').read_bytes())
    except BaseException:module.unlink();raise
    print('Fixed legacy render protocol added; no model/service restart, no GPU workload submitted')
if __name__=='__main__':main()
