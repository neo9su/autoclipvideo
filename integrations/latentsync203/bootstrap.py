# coding: utf-8
from pathlib import Path
import subprocess, urllib.request,zipfile,shutil,json,time
root=Path(r'F:\aid-models\latentsync-1.5');root.mkdir(parents=True,exist_ok=True)
print('ROOT',root,flush=True)
py=Path(r'C:\Python311\python.exe')
assert py.exists()
if not (root/'venv/Scripts/python.exe').exists():subprocess.run([str(py),'-m','venv',str(root/'venv')],check=True)
py=root/'venv/Scripts/python.exe'
repo=root/'repo'
if not repo.exists():
 archive=root/'source.zip';urllib.request.urlretrieve('https://codeload.github.com/bytedance/LatentSync/zip/36ca2a32e942',archive)
 with zipfile.ZipFile(archive) as z:z.extractall(root/'source')
 shutil.move(str(next((root/'source').iterdir())),repo)
subprocess.run([str(py),'-m','pip','install','--disable-pip-version-check','--timeout','20','--retries','1','--index-url','https://pypi.tuna.tsinghua.edu.cn/simple','-r',str(repo/'requirements.txt')],check=True,stdout=sys.stdout,stderr=sys.stderr)
print('DEPENDENCIES_READY',flush=True)
