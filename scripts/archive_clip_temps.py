"""Checksummed stream archive for inactive clip intermediates, never source video."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import uuid


def fingerprint(plan):return hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()


def validate(plan):
    if not re.fullmatch('[0-9a-f]{16}',plan['job_id']):raise ValueError('Invalid job directory')
    names=set()
    for f in plan['files']:
        if not re.fullmatch(r'seg\d+\.mp4',f['name']) or f['name'] in names:raise ValueError('Only unique clip intermediates are allowed')
        names.add(f['name'])
        if not isinstance(f['bytes'],int) or f['bytes']<0 or not re.fullmatch('[0-9a-f]{64}',f['sha256']):raise ValueError('Invalid file evidence')
    if not names:raise ValueError('Empty job')


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(4*1024**2),b''):h.update(block)
    return h.hexdigest()


def send(root,plan,stream):
    validate(plan);base=Path(root)/plan['job_id']
    stream.write(json.dumps(plan).encode()+b'\n')
    for f in plan['files']:
        path=base/f['name'];s=path.stat()
        if (s.st_size,s.st_mtime_ns)!=(f['bytes'],f['mtime_ns']):raise ValueError('Source changed before transfer')
        with path.open('rb') as source:shutil.copyfileobj(source,stream,4*1024**2)
    stream.flush()


def receive(root,stream):
    header=stream.readline(1024*1024)
    if not header.endswith(b'\n'):raise ValueError('Invalid archive header')
    plan=json.loads(header);validate(plan);root=Path(root);root.mkdir(parents=True,exist_ok=True)
    target=root/plan['job_id'];stage=root/(plan['job_id']+'.partial-'+uuid.uuid4().hex)
    if target.exists():raise ValueError('Archive already exists')
    stage.mkdir()
    for f in plan['files']:
        path=stage/f['name'];remaining=f['bytes'];h=hashlib.sha256()
        with path.open('xb') as dest:
            while remaining:
                block=stream.read(min(remaining,4*1024**2))
                if not block:raise ValueError('Truncated transfer; source must be retained')
                dest.write(block);h.update(block);remaining-=len(block)
            dest.flush();os.fsync(dest.fileno())
        if h.hexdigest()!=f['sha256']:raise ValueError('Transfer checksum mismatch; source must be retained')
        os.utime(path,ns=(f['mtime_ns'],f['mtime_ns']))
    (stage/'manifest.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
    stage.rename(target)
    return {'fingerprint':fingerprint(plan),'files':len(plan['files']),'bytes':sum(f['bytes'] for f in plan['files'])}


def reclaim(root,plan,receipt):
    validate(plan)
    if receipt.get('fingerprint')!=fingerprint(plan):raise ValueError('Archive receipt mismatch')
    base=Path(root)/plan['job_id']
    for f in plan['files']:
        p=base/f['name'];s=p.stat()
        if (s.st_size,s.st_mtime_ns)!=(f['bytes'],f['mtime_ns']) or digest(p)!=f['sha256']:raise ValueError('Source changed; retain local files')
    for f in plan['files']:(base/f['name']).unlink()
    return receipt


def restore(root,archive):
    """Restore from a mounted/copied archive; never overwrite newer local files."""
    archive=Path(archive);plan=json.loads((archive/'manifest.json').read_text());validate(plan)
    base=Path(root)/plan['job_id'];base.mkdir(parents=True,exist_ok=True)
    for f in plan['files']:
        dest=base/f['name']
        if dest.exists():raise ValueError('Restore would overwrite existing data')
        if digest(archive/f['name'])!=f['sha256']:raise ValueError('Archive checksum mismatch')
    for f in plan['files']:
        dest=base/f['name'];temporary=base/(f['name']+'.restore-'+uuid.uuid4().hex)
        shutil.copy2(archive/f['name'],temporary)
        if digest(temporary)!=f['sha256']:raise ValueError('Restore copy mismatch')
        os.replace(temporary,dest)
    return len(plan['files'])
