from pathlib import Path
import subprocess,urllib.request,zipfile,shutil,sys,json,hashlib
root=Path(r'F:\aid-models\musetalk-1.5');root.mkdir(parents=True,exist_ok=True)
py=root/'venv/Scripts/python.exe'
if not py.exists():subprocess.run([r'C:\Python311\python.exe','-m','venv',str(root/'venv')],check=True)
def pip(*args):subprocess.run([str(py),'-m','pip','install','--disable-pip-version-check','--timeout','60','--retries','1',*args],check=True)
repo=root/'repo'
if not repo.exists():
 z=root/'source.zip';urllib.request.urlretrieve('https://codeload.github.com/TMElyralab/MuseTalk/zip/0a89dec45a0192b824e3cf4daf96c239440c5ed8',z)
 with zipfile.ZipFile(z) as h:h.extractall(root/'source')
 shutil.move(str(next((root/'source').iterdir())),repo)
pip('--index-url','https://pypi.tuna.tsinghua.edu.cn/simple',*[str(p) for p in (root/'wheels').glob('torch*.whl')])
pip('--index-url','https://pypi.tuna.tsinghua.edu.cn/simple','wheel','scipy==1.10.1','scikit-image==0.22.0','numpy==1.23.5')
pip('--index-url','https://pypi.tuna.tsinghua.edu.cn/simple','--no-build-isolation','chumpy==0.70')
# Inference-only dependency set: omit training TensorFlow/TensorBoard and web UI.
pip('--index-url','https://pypi.tuna.tsinghua.edu.cn/simple','diffusers==0.30.2','accelerate==0.28.0','numpy==1.23.5','opencv-python==4.9.0.80','soundfile==0.12.1','transformers==4.39.2','huggingface_hub==0.30.2','librosa==0.11.0','einops==0.8.1','imageio[ffmpeg]','omegaconf','ffmpeg-python','scipy','scikit-image','mmengine==0.10.7','mmdet==3.1.0','mmpose==1.1.0')
pip('--index-url','https://pypi.tuna.tsinghua.edu.cn/simple',str(root/'wheels/mmcv-2.0.1-cp311-cp311-win_amd64.whl'))
print('DEPENDENCIES_READY',flush=True)
