"""Standalone CPU worker. Deploy beside an isolated vendor directory and backend."""
import json
from pathlib import Path
import sys

root=Path(__file__).resolve().parent
sys.path.insert(0,str(root/'vendor'))
sys.path.insert(0,str(root.parent/'backend'))
from wig_homophone_review import retrieve

if __name__=='__main__':
    data=sys.stdin.buffer.read(2*1024*1024+1)
    if len(data)>2*1024*1024:raise ValueError('Review payload too large')
    payload=json.loads(data)
    print(json.dumps({'candidates':retrieve(payload['cues'],payload['products'])},ensure_ascii=False))
