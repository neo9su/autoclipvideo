"""Independent CPU segmentation evidence; does not assign SKU or publish decisions."""
from pathlib import Path
import argparse
import hashlib
import json
import time
import numpy as np
from PIL import Image,ImageDraw
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision


def run(root):
    folder=root/'hair-segmentation-review';folder.mkdir(exist_ok=True)
    model=folder/'selfie_multiclass_256x256.tflite'
    options=vision.ImageSegmenterOptions(base_options=python.BaseOptions(
        model_asset_path=str(model),delegate=python.BaseOptions.Delegate.CPU),
        running_mode=vision.RunningMode.IMAGE,output_category_mask=True)
    rows=[]
    with vision.ImageSegmenter.create_from_options(options) as segmenter:
        for start in [455,547,1423]:
            board=Image.open(root/f'qwen-dense-evidence-{start}.jpg').convert('RGB')
            width,height=board.width//4,board.height//2
            output=Image.new('RGB',(board.width,board.height))
            for i in range(8):
                x,y=i%4*width,i//4*height
                image=board.crop((x,y,x+width,y+height));rgb=np.array(image)
                before=time.perf_counter()
                result=segmenter.segment(mp.Image(image_format=mp.ImageFormat.SRGB,data=rgb))
                elapsed=time.perf_counter()-before
                mask=result.category_mask.numpy_view().copy()
                if mask.ndim==3 and mask.shape[-1]==1:
                    mask=mask[:,:,0]
                assert mask.ndim==2, f'Unexpected category-mask shape: {mask.shape}'
                if mask.shape!=rgb.shape[:2]:
                    mask=np.array(Image.fromarray(mask).resize(image.size,Image.Resampling.NEAREST))
                assert mask.shape==rgb.shape[:2]
                hair=mask==1;face=mask==3;accessory=mask==5
                colored=rgb.astype(float)
                colored[hair]=.5*colored[hair]+.5*np.array([0,255,0])
                colored[accessory]=.5*colored[accessory]+.5*np.array([255,0,0])
                frame=Image.fromarray(colored.astype('uint8'))
                ImageDraw.Draw(frame).text((8,8),f'{start+i} hair={hair.mean():.3f}',fill='white',stroke_width=2,stroke_fill='black')
                output.paste(frame,(x,y))
                rows.append({'nominal_source_second':start+i,'sampling':'ffmpeg fps=1 contact sheet; allow subsecond offset',
                    'hair_fraction':round(float(hair.mean()),5),'accessory_fraction':round(float(accessory.mean()),5),
                    'hair_to_face_ratio':round(float(hair.sum()/face.sum()),4) if face.sum() else None,
                    'elapsed_cpu_seconds':round(elapsed,4)})
            output.save(folder/f'masks-{start}.jpg')
    report={'model_sha256':hashlib.sha256(model.read_bytes()).hexdigest(),'delegate':'CPU','gpu_used':False,
            'observations':rows,'scope':'hair/accessory masks only; not wig-wearing classification or SKU truth',
            'production_changed':False}
    (folder/'mask-review.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);run(parser.parse_args().root.resolve())
