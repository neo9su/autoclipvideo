from pathlib import Path
import json,urllib.request,hashlib,shutil,concurrent.futures
root=Path(r'F:\aid-models\musetalk-1.5')
def fetch(x):
 p=root/x['dest'];p.parent.mkdir(parents=True,exist_ok=True)
 if not p.exists():
  print('DOWNLOAD',x['dest'],flush=True)
  with urllib.request.urlopen(x['url'],timeout=180) as h,p.with_suffix(p.suffix+'.part').open('wb') as w:shutil.copyfileobj(h,w,1024*1024)
  p.with_suffix(p.suffix+'.part').replace(p)
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 assert h.hexdigest()==x['hash'],str(p)
 print('VERIFIED',x['dest'],flush=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(fetch,json.loads((root/'transfer.json').read_text())))
print('TRANSFER_READY',flush=True)
