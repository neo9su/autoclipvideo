"""Pilot-only mouth fusion: preserve original pixels outside a lip-local mask."""
import cv2
import numpy as np
import torch
from PIL import Image

def stabilize_boxes(coords):
    """Centered three-frame filter, bounded to 1% of box size; no temporal image blur."""
    out=[]
    for i, box in enumerate(coords):
        b=np.asarray(box,dtype=float)
        if i==0 or i==len(coords)-1 or b[2]<=b[0] or b[3]<=b[1]:
            out.append(tuple(box));continue
        before=np.asarray(coords[i-1],dtype=float);after=np.asarray(coords[i+1],dtype=float)
        w,h=b[2]-b[0],b[3]-b[1];scale=np.array([w,h,w,h])
        if any(q[2]<=q[0] or q[3]<=q[1] for q in (before,after)) or np.max(np.abs(before-after)/scale)>.08:
            out.append(tuple(box));continue
        target=(before+2*b+after)/4
        result=np.rint(b+np.clip(target-b,-.01*scale,.01*scale)).astype(int)
        out.append(tuple(result))
    return out

class LocalizedBlend:
    def __init__(self):
        self.previous=None
        self.coverage=[]

    @staticmethod
    def mouth_mask(bgr,fp):
        image=Image.fromarray(cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB)).resize((512,512),Image.Resampling.BILINEAR)
        device=next(fp.net.parameters()).device
        with torch.no_grad():
            labels=fp.net(fp.preprocess(image).unsqueeze(0).to(device))[0].argmax(1)[0].cpu().numpy()
        mask=np.isin(labels,[11,12,13]).astype(np.uint8)
        return cv2.resize(mask,(bgr.shape[1],bgr.shape[0]),interpolation=cv2.INTER_NEAREST)

    def __call__(self,image,face,box,fp):
        x,y,x2,y2=map(int,box)
        if not (0<=x<x2<=image.shape[1] and 0<=y<y2<=image.shape[0]):raise ValueError('Invalid face crop')
        original=image[y:y2,x:x2];h,w=original.shape[:2]
        core=np.maximum(self.mouth_mask(original,fp),self.mouth_mask(face,fp))
        if not np.any(core):raise ValueError('No reliable mouth region; do not fabricate a mask')
        # Union erases original lips and covers the new mouth, including open-mouth motion.
        radius=max(2,round(.025*min(w,h)))
        kernel=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(2*radius+1,2*radius+1))
        core=cv2.dilate(core,kernel)
        if float(core.mean())>.30:raise ValueError('Mouth mask unexpectedly broad')
        feather=max(1,round(.012*min(w,h)))
        alpha=cv2.GaussianBlur(core.astype(np.float32),(2*feather+1,2*feather+1),0)
        # Smooth only mask edges in face-relative coordinates; never average mouth images.
        if self.previous is not None:
            prev=cv2.resize(self.previous,(w,h),interpolation=cv2.INTER_LINEAR)
            alpha=.8*alpha+.2*prev
        alpha=np.maximum(alpha,core.astype(np.float32))
        alpha[alpha<.01]=0
        self.previous=alpha.copy()
        self.coverage.append(float(np.mean(alpha>0)))
        a=alpha[:,:,None]
        blended=np.rint(original.astype(np.float32)*(1-a)+face.astype(np.float32)*a).clip(0,255).astype(np.uint8)
        result=image.copy();result[y:y2,x:x2]=blended
        return result
