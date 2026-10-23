"""Move verified old generated videos out of production, keeping source media safe."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re


def generated_time(name):
    if re.match(r'merged_\d+_',name):
        match=re.search(r'_(20\d{6})_(\d{6})(?:_|\.)',name)
        if match:return datetime.strptime(''.join(match.groups()),'%Y%m%d%H%M%S').replace(tzinfo=timezone.utc).timestamp()
    match=re.match(r'(?:director_output|qianchuan|creative|director)_(\d{10})(?:_|\.)',name)
    return int(match[1]) if match else None


def evidence(path):
    s=path.stat();return {'dev':s.st_dev,'inode':s.st_ino,'bytes':s.st_size,'mtime_ns':s.st_mtime_ns}


def save(path,data):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temp,path)


def preview(roots,cutoff,protected):
    rows=[];protected={x.casefold() for x in protected}
    for scope,root in roots.items():
        for p in Path(root).iterdir():
            if p.is_symlink() or not p.is_file() or p.suffix.lower() not in ('.mp4','.mov','.mkv','.webm'):continue
            stamp=generated_time(p.name)
            if stamp is None or stamp>=cutoff or p.name.casefold() in protected:continue
            e=evidence(p)
            if e['mtime_ns']/1e9<cutoff:rows.append({'scope':scope,'source':str(p),**e})
    return rows


def apply(rows,batch):
    batch=Path(batch);batch.mkdir(parents=True,exist_ok=False)
    data={'state':'prepared','files':[]}
    for row in rows:
        dest=batch/'files'/row['scope']/Path(row['source']).name
        data['files'].append(dict(row,destination=str(dest)))
    journal=batch/'manifest.json';save(journal,data)
    for row in data['files']:
        source=Path(row['source']);dest=Path(row['destination'])
        if evidence(source)!={k:row[k] for k in ('dev','inode','bytes','mtime_ns')}:raise ValueError('Source changed')
        dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists():raise ValueError('Quarantine target exists')
        source.rename(dest)
        if evidence(dest)!={k:row[k] for k in ('dev','inode','bytes','mtime_ns')}:raise ValueError('Moved file identity mismatch')
    data['state']='applied';save(journal,data);return data


def restore(journal):
    journal=Path(journal);data=json.loads(journal.read_text(encoding='utf-8'))
    for row in data['files']:
        source=Path(row['source']);dest=Path(row['destination'])
        if not dest.exists():continue
        if source.exists():raise ValueError('New source exists; refuse overwrite')
        if evidence(dest)!={k:row[k] for k in ('dev','inode','bytes','mtime_ns')}:raise ValueError('Quarantined file changed')
    for row in data['files']:
        source=Path(row['source']);dest=Path(row['destination'])
        if dest.exists():
            os.link(dest,source)  # Atomic no-overwrite restore on the same volume.
            dest.unlink()
    data['state']='restored';save(journal,data);return data
