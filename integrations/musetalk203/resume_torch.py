from pathlib import Path
import urllib.request,json,hashlib,concurrent.futures,shutil
r=Path(r'F:\aid-models\musetalk-1.5');x=next(x for x in json.loads((r/'transfer.json').read_text()) if '/torch-' in x['dest']);p=r/x['dest'];size=2619152705;start=p.stat().st_size
chunks=[]
for a in range(start,size,32*1024*1024):chunks.append((a,min(size-1,a+32*1024*1024-1)))
def get(ab):
 a,b=ab;dst=r/'wheels'/('chunk-'+str(a))
 if dst.exists() and dst.stat().st_size==b-a+1:return dst
 req=urllib.request.Request(x['url']+'?range='+str(a),headers={'Range':f'bytes={a}-{b}'})
 with urllib.request.urlopen(req,timeout=90) as h:
  assert h.status==206 and h.headers.get('Content-Range')==f'bytes {a}-{b}/{size}'
  with dst.open('wb') as w:shutil.copyfileobj(h,w,1024*1024)
 assert dst.stat().st_size==b-a+1
 print('CHUNK',a,flush=True);return dst
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:files=list(pool.map(get,chunks))
with p.open('ab') as w:
 for f in files:
  with f.open('rb') as h:shutil.copyfileobj(h,w,1024*1024)
h=hashlib.sha256()
with p.open('rb') as f:
 for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
assert h.hexdigest()==x['hash']
for f in files:f.unlink()
print('TORCH_VERIFIED',flush=True)
