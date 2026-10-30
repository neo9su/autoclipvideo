import sys
from pathlib import Path
sys.path.insert(0,str(Path(r'F:\aid-models\musetalk-1.5\repo')))
import numpy as np
from musetalk.utils.localized_blend import LocalizedBlend,stabilize_boxes
b=[(10,10,110,110),(12,12,112,112),(10,10,110,110)]
assert stabilize_boxes(b)[1]==(11,11,111,111)
fast=[(0,0,100,100),(40,40,140,140),(80,80,180,180)]
assert stabilize_boxes(fast)==fast
m=LocalizedBlend()
def mask(image,fp):
 a=np.zeros(image.shape[:2],dtype=np.uint8);a[60:70,40:60]=1;return a
m.mouth_mask=mask
image=np.full((200,200,3),80,dtype=np.uint8);face=np.full((100,100,3),180,dtype=np.uint8)
out=m(image,face,[50,50,150,150],None)
assert np.array_equal(out[:100],image[:100])
assert np.array_equal(out[:,0:50],image[:,0:50])
assert np.all(out[110:120,90:110]==180)
# Mask stabilizing must not mix the previous generated mouth pixels.
out2=m(image,np.full_like(face,220),[50,50,150,150],None)
assert np.all(out2[110:120,90:110]==220)
m.mouth_mask=lambda image,fp:np.zeros(image.shape[:2],dtype=np.uint8)
try:m(image,face,[50,50,150,150],None)
except ValueError:pass
else:raise AssertionError('Missing mouth should fail')
print('PASS: bounded box smoothing, fast motion preserved, outer pixels preserved, current mouth opaque, missing mask rejected')
