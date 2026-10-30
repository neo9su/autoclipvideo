"""Verified, reversible cold-directory relocation with original-path mapping."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid


def linked(path):
    return path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction())


def inventory(root):
    result={}
    for base,dirs,files in os.walk(root):
        for name in dirs+files:
            if linked(Path(base)/name):raise ValueError('Nested links are not supported')
        for name in files:
            path=Path(base)/name;before=path.stat();digest=hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda:stream.read(4*1024*1024),b''):digest.update(chunk)
            after=path.stat()
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('Source changed during hashing')
            result[str(path.relative_to(root))]={'bytes':after.st_size,'sha256':digest.hexdigest()}
    return result


def save(journal,data):
    temporary=journal.with_suffix('.tmp');temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temporary,journal)


def map_directory(path,target):
    if os.name=='nt':
        for p in (path,target):
            if any(c in str(p) for c in '&|<>%^"!\r\n'):raise ValueError('Unsafe junction path')
        subprocess.run(['cmd','/d','/c','mklink','/J',str(path),str(target)],check=True,capture_output=True)
    else:path.symlink_to(target,target_is_directory=True)


def remove_mapping(path):
    if not linked(path):raise ValueError('Expected a directory mapping')
    if os.name=='nt' and not path.is_symlink():os.rmdir(path)
    else:path.unlink()


def relocate(source,destination,journal,reserve_bytes=40*1024**3):
    source=Path(source).absolute();destination=Path(destination).absolute();journal=Path(journal).absolute()
    if not source.is_dir() or linked(source) or destination.exists() or journal.exists():raise ValueError('Source or destination state changed')
    if source in destination.parents or destination in source.parents or source==destination:raise ValueError('Overlapping trees')
    destination.parent.mkdir(parents=True,exist_ok=True);journal.parent.mkdir(parents=True,exist_ok=True)
    files=inventory(source)
    if not files:raise ValueError('Empty directory')
    size=sum(v['bytes'] for v in files.values())
    if shutil.disk_usage(destination.parent).free<size+reserve_bytes:raise ValueError('Destination reserve would be exhausted')
    data={'source':str(source),'destination':str(destination),'files':files,'bytes':size,'state':'prepared'};save(journal,data)
    shutil.copytree(source,destination,copy_function=shutil.copy2)
    if inventory(destination)!=files or inventory(source)!=files:raise ValueError('Copy verification failed; original retained')
    old=source.with_name(source.name+'.relocation-original-'+uuid.uuid4().hex)
    data.update(state='verified',original=str(old));save(journal,data)
    source.rename(old)
    try:
        map_directory(source,destination)
        if source.resolve()!=destination.resolve() or inventory(source)!=files:raise ValueError('Mapped path verification failed')
    except BaseException:
        if linked(source):remove_mapping(source)
        old.rename(source)
        raise
    data['state']='mapped';save(journal,data)
    # This removes only the verified redundant copy. Every byte remains at the
    # destination and is reachable through the original source path.
    if inventory(old)!=files or inventory(destination)!=files:
        raise ValueError('Content changed after mapping; both copies retained for recovery')
    shutil.rmtree(old)
    data['state']='applied';save(journal,data)
    return data


def restore(journal):
    journal=Path(journal);data=json.loads(journal.read_text(encoding='utf-8'))
    if data['state']!='applied':raise ValueError('Batch needs state-specific recovery')
    source=Path(data['source']);destination=Path(data['destination'])
    if not linked(source) or source.resolve()!=destination.resolve():raise ValueError('Mapping drifted')
    if inventory(destination)!=data['files']:raise ValueError('Destination changed; preserve newer data')
    if shutil.disk_usage(source.parent).free<data['bytes']+1024**3:raise ValueError('Insufficient restore capacity')
    staging=source.with_name(source.name+'.restore-'+uuid.uuid4().hex)
    shutil.copytree(destination,staging,copy_function=shutil.copy2)
    if inventory(staging)!=data['files']:raise ValueError('Restore copy mismatch')
    remove_mapping(source)
    try:staging.rename(source)
    except BaseException:
        map_directory(source,destination)
        raise
    data['state']='restored';save(journal,data)
    # Retain the destination copy as a backup; do not delete newer user data.
    return data
