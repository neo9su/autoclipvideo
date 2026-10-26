"""Prepare a SHA-guarded worker upgrade for explicit AID administrator review."""
from pathlib import Path
import argparse,hashlib,json
from patch_worker import patch

def sha(data):return hashlib.sha256(data).hexdigest()
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    old=args.source.read_bytes();new=patch(old.decode('utf8')).encode('utf8');module=Path(__file__).with_name('legacy_clip_worker.py').read_bytes()
    args.output.mkdir(exist_ok=False,parents=True)
    for name,data in [('worker.before.py',old),('worker.after.py',new),('legacy_clip_worker.py',module)]: (args.output/name).write_bytes(data)
    (args.output/'manifest.json').write_text(json.dumps(dict(worker_basename=args.source.name,before=sha(old),after=sha(new),module_sha=sha(module)),indent=2))
    (args.output/'activate.py').write_bytes(Path(__file__).with_name('activate_bundle.py').read_bytes())
    print(args.output)
if __name__=='__main__':main()
