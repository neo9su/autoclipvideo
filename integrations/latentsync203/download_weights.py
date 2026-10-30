from pathlib import Path
import subprocess,sys,concurrent.futures,zipfile
r=Path(r'F:\aid-models\latentsync-1.5');sys.stdout=open(r/'weights.log','a',buffering=1);sys.stderr=sys.stdout
repo=r/'repo';rev='32a20d29aead0498e3e885e90dbbe8027da1b61b'
files=[('https://hf-mirror.com/ByteDance/LatentSync-1.5/resolve/'+rev+'/'+n,repo/'checkpoints'/n) for n in ['latentsync_unet.pt','whisper/tiny.pt']]
files += [('https://hf-mirror.com/stabilityai/sd-vae-ft-mse/resolve/main/'+n,repo/'checkpoints/vae'/n) for n in ['config.json','diffusion_pytorch_model.bin']]
files += [('https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip',repo/'checkpoints/auxiliary/buffalo_l.zip')]
def download(item):
 url,p=item;p.parent.mkdir(parents=True,exist_ok=True)
 if p.exists():return
 print('Downloading',p.name,flush=True)
 tmp=p.with_suffix(p.suffix+'.part')
 subprocess.run(['curl.exe','-f','-L','-sS','--connect-timeout','30','--max-time','2400','--retry','2','-o',str(tmp),url],check=True,stdout=sys.stdout,stderr=sys.stderr)
 tmp.replace(p);print('Ready',p.name,p.stat().st_size,flush=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(download,files))
with zipfile.ZipFile(repo/'checkpoints/auxiliary/buffalo_l.zip') as z:z.extractall(repo/'checkpoints/auxiliary/models/buffalo_l')
p=repo/'scripts/inference.py';s=p.read_text();s=s.replace('"stabilityai/sd-vae-ft-mse"','"checkpoints/vae"');p.write_text(s)
print('WEIGHTS_READY',flush=True)
