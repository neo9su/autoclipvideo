from pathlib import Path
import json,shutil,hashlib
root=Path(r'F:\aid-models\musetalk-1.5');models=root/'repo/models';incoming=root/'incoming'
f={'TMElyralab/MuseTalk':'','openai/whisper-tiny':'whisper','yzd-v/DWPose':'dwpose','ManyOtherFunctions/face-parse-bisent':'face-parse-bisent'}
for x in json.loads((root/'weights.json').read_text()):
 src=incoming/x['file'].replace('/','__');dst=models/f[x['repo']]/x['file'];dst.parent.mkdir(parents=True,exist_ok=True)
 if x['sha256']:
  h=hashlib.sha256()
  with src.open('rb') as s:
   for b in iter(lambda:s.read(1024*1024),b''):h.update(b)
  assert h.hexdigest()==x['sha256'],str(src)
 shutil.move(src,dst)
vae=models/'sd-vae';vae.mkdir(exist_ok=True)
for n in ['config.json','diffusion_pytorch_model.bin']:shutil.copy2(Path(r'F:\aid-models\latentsync-1.5\repo\checkpoints\vae')/n,vae/n)
shutil.move(incoming/'s3fd.pth',root/'repo/musetalk/utils/face_detection/detection/sfd/s3fd.pth')
(root/'Weights.log').write_text('WEIGHTS_READY\n');print('WEIGHTS_READY')
