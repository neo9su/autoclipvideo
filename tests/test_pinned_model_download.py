import hashlib
import importlib.util
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('pinned_download',Path(__file__).resolve().parents[1]/'scripts'/'download_pinned_vision_model.py')
download=importlib.util.module_from_spec(spec);spec.loader.exec_module(download)


class Response:
    def __init__(self,data,status=200,headers=None):self.data=data;self.status=status;self.headers=headers or {}
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,n):data,self.data=self.data[:n],self.data[n:];return data


def item(data):return {'name':'model.safetensors','size':len(data),'sha256':hashlib.sha256(data).hexdigest()}


def test_resume_verified_data_before_promotion(tmp_path,monkeypatch):
    data=b'complete weights';(tmp_path/'model.safetensors.partial').write_bytes(data[:4])
    monkeypatch.setattr(download.request,'urlopen',lambda *a,**k:Response(data[4:],206,{'Content-Range':f'bytes 4-{len(data)-1}/{len(data)}'}))
    download.download_file('https://example.invalid/pinned',tmp_path,item(data))
    assert (tmp_path/'model.safetensors').read_bytes()==data


def test_wrong_resume_response_and_bad_checksum_are_retained(tmp_path,monkeypatch):
    data=b'complete weights';partial=tmp_path/'model.safetensors.partial';partial.write_bytes(data[:4])
    monkeypatch.setattr(download.request,'urlopen',lambda *a,**k:Response(data))
    with pytest.raises(ValueError):download.download_file('https://example.invalid/pinned',tmp_path,item(data))
    assert partial.read_bytes()==data[:4] and not (tmp_path/'model.safetensors').exists()
    partial.write_bytes(b'X'*len(data))
    with pytest.raises(ValueError):download.download_file('https://example.invalid/pinned',tmp_path,item(data))
    assert not (tmp_path/'model.safetensors').exists()
