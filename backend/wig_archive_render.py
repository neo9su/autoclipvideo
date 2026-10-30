"""CPU-only precise source cuts, published atomically with recoverable batches."""
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import socket
import subprocess
import uuid
from wig_library_index import encoded, video_info
from wig_preprocess import build_asset_name

VERSION = 'cpu-source-cut-v1'


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as f:
        while block := f.read(4*1024*1024):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    import os
    path.parent.mkdir(parents=True, exist_ok=True)
    temp=path.with_suffix('.tmp')
    with temp.open('w',encoding='utf-8') as f:
        f.write(encoded(value));f.flush();os.fsync(f.fileno())
    temp.replace(path)


def precise_cut(source, target, start, end):
    # Seek after opening the input so decoding honours the requested source
    # frame, rather than copying from the preceding video keyframe.
    subprocess.run(['ffmpeg','-nostdin','-v','error','-n','-i',str(source),
        '-ss',f'{start:.6f}','-t',f'{end-start:.6f}',
        '-map','0:v:0','-map','0:a:0?','-map_metadata','-1',
        '-c:v','libx264','-preset','fast','-crf','18','-threads','2',
        '-c:a','aac','-b:a','192k','-movflags','+faststart',str(target)],
        capture_output=True,timeout=7200,check=True)


class ArchiveRenderer:
    def __init__(self, index, storage):
        self.index=index
        self.storage=Path(storage).resolve()
        self.root=self.storage/'_wig_library'

    def prepare(self, plan_id):
        if len(plan_id)!=64 or any(c not in '0123456789abcdef' for c in plan_id):
            raise ValueError('无效计划ID')
        with self.index.connect() as con:
            row=con.execute('SELECT * FROM plans WHERE plan_id=?',(plan_id,)).fetchone()
            if row is None or row['state']!='active':
                raise ValueError('计划不存在或已撤销')
            plan=json.loads(row['document'])
            asset=con.execute('SELECT * FROM assets WHERE asset_id=?',(row['asset_id'],)).fetchone()
            locations=con.execute('SELECT * FROM locations WHERE asset_id=? AND recording_id=? AND host=?',
                (row['asset_id'],row['recording_id'],socket.gethostname())).fetchall()
        if asset is None:
            raise ValueError('缺少原片内容登记')
        sources=[Path(r['path']) for r in locations
                 if Path(r['path']).resolve().is_relative_to(self.storage) and Path(r['path']).is_file()]
        if not sources:
            raise ValueError('本机没有可用原片')
        segments=plan.get('segments') or []
        if not segments or any(s.get('status')!='ready' for s in segments):
            raise ValueError('分段身份尚未核验，不执行切片')
        duration=json.loads(asset['metadata'])['duration_seconds']
        for s in segments:
            start,end=s['start_sec'],s['end_sec']
            if not all(math.isfinite(t) for t in (start,end)) or start<0 or end<=start or end>duration:
                raise ValueError('分段时间超出源录像')
        for i,a in enumerate(segments):
            for b in segments[i+1:]:
                if min(a['end_sec'],b['end_sec'])>max(a['start_sec'],b['start_sec']):
                    raise ValueError('展示区间重叠，不执行切片')
        return plan,dict(asset),sources[0]

    def export(self, plan_id):
        plan,asset,source=self.prepare(plan_id)
        batch=hashlib.sha256((VERSION+plan_id).encode()).hexdigest()[:32]
        journal=self.root/'export_journals'/(batch+'.json')
        final=self.root/'exports'/batch
        staging=self.root/'export_staging'/batch
        if journal.exists():
            old=json.loads(journal.read_text(encoding='utf-8'))
            if old['state']=='complete':
                self.validate_files(final,old)
                return old
            raise ValueError('该计划已有未完成或已撤回的批次，请先恢复处理')
        # A dedicated directory also excludes concurrent exporters of this plan.
        staging.mkdir(parents=True,exist_ok=False)
        before=source.stat()
        job={'batch_id':batch,'plan_id':plan_id,'asset_id':asset['asset_id'],
             'source_sha256':asset['sha256'],'source_path':str(source),
             'source_host':socket.gethostname(),'source_size_bytes':asset['size_bytes'],
             'source_video':json.loads(asset['metadata']),'subtitle_sha256':plan.get('subtitle_sha256'),
             'time_basis':'original_video_seconds','renderer':VERSION,'state':'prepared',
             'created_at':datetime.now(timezone.utc).isoformat(),'files':[],'media_created':False}
        write_json(journal,job)
        try:
            if sha256(source)!=asset['sha256']:
                raise ValueError('源录像内容与登记不符')
            for segment in plan['segments']:
                folder=build_asset_name(segment.get('hairstyle_name'),segment.get('color'),segment.get('features') or []).encode('utf-8')[:120].decode('utf-8',errors='ignore').rstrip(' .')
                if folder.upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:
                    folder += '_'
                relative=Path(folder)/(segment['segment_id']+'.mp4')
                target=staging/relative;target.parent.mkdir(parents=True,exist_ok=True)
                precise_cut(source,target,segment['start_sec'],segment['end_sec'])
                info=video_info(target)
                wanted=segment['end_sec']-segment['start_sec']
                if abs(info['duration_seconds']-wanted)>0.15:
                    raise ValueError('导出时长未通过源时间校验')
                item={**segment,'relative_output':relative.as_posix(),'output_sha256':sha256(target),
                      'size_bytes':target.stat().st_size,'video':info}
                job['files'].append(item)
                write_json(journal,job)
            after=source.stat()
            if (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino):
                raise ValueError('切片期间原录像发生变化')
            with self.index.connect() as con:
                current=con.execute('SELECT state,document FROM plans WHERE plan_id=?',(plan_id,)).fetchone()
                if current is None or current['state']!='active' or json.loads(current['document'])!=plan:
                    raise ValueError('切片期间计划状态已变化，保留临时结果')
            # Retain a reproducible source-time manifest beside the outputs.
            job.update(state='complete',media_created=True)
            write_json(staging/'source-manifest.json',job)
            final.parent.mkdir(parents=True,exist_ok=True)
            staging.rename(final)
            write_json(journal,job)
            return job
        except BaseException:
            # If publication succeeded but journal writing failed, keep prepared
            # so recovery can recognise the complete, validated directory.
            job['state']='prepared' if final.exists() else 'failed'
            write_json(journal,job)
            raise

    @staticmethod
    def validate_files(directory, job):
        if not job['files']:
            raise ValueError('批次无已校验文件')
        root=directory.resolve()
        for f in job['files']:
            p=(directory/f['relative_output']).resolve()
            if not p.is_relative_to(root) or not p.is_file() or p.stat().st_size!=f['size_bytes'] or sha256(p)!=f['output_sha256']:
                raise ValueError('输出文件缺失、路径冲突或内容已改变')

    def batch_state(self, batch, action):
        if len(batch)!=32 or any(c not in '0123456789abcdef' for c in batch):
            raise ValueError('无效切片批次')
        journal=self.root/'export_journals'/(batch+'.json')
        job=json.loads(journal.read_text(encoding='utf-8'))
        final=self.root/'exports'/batch
        staging=self.root/'export_staging'/batch
        trash=self.root/'recoverable_exports'/batch
        if action=='retry':
            if job['state'] not in ('failed','retrying') and not (job['state']=='withdrawn' and job.get('previous_state')=='failed'):
                raise ValueError('只能重试已停止的失败批次')
            if final.exists():
                raise ValueError('已存在落位文件，先检查恢复')
            if job['state']!='retrying':
                token=uuid.uuid4().hex
                job.update(state='retrying',retry_from='recoverable_exports' if trash.exists() else 'export_staging',
                           attempt_directory='export_attempts/'+batch+'_'+token,
                           attempt_journal='export_journals/attempts/'+batch+'_'+token+'.json')
                write_json(journal,job)
            origin=self.root/job['retry_from']/batch
            retained=self.root/job['attempt_directory']
            retained.parent.mkdir(parents=True,exist_ok=True)
            if origin.exists() and not retained.exists():
                origin.rename(retained)
            elif not (retained.exists() and not origin.exists()):
                raise ValueError('失败临时目录冲突')
            audit=self.root/job['attempt_journal'];audit.parent.mkdir(parents=True,exist_ok=True)
            journal.rename(audit)
            return self.export(job['plan_id'])
        if action in ('restore','recover') and job['state']=='complete':
            self.validate_files(final,job)
            return job
        if action=='withdraw' and job['state']=='withdrawn':
            if not trash.is_dir():
                raise ValueError('已撤回目录缺失')
            return job
        if action=='withdraw' and job['state']=='withdrawing':
            origin=self.root/job['origin']/batch
            if origin.exists() and not trash.exists():
                trash.parent.mkdir(parents=True,exist_ok=True);origin.rename(trash)
            elif not (trash.exists() and not origin.exists()):
                raise ValueError('撤回路径冲突')
            job['state']='withdrawn';write_json(journal,job)
            return job
        if action=='withdraw' and job['state']=='prepared' and final.is_dir():
            job=self.batch_state(batch,'recover')
        if action=='recover':
            if job['state']!='prepared' or not final.is_dir():
                raise ValueError('批次尚未完成原子落位，不能恢复为完成')
            published=json.loads((final/'source-manifest.json').read_text(encoding='utf-8'))
            if published['batch_id']!=batch or published['plan_id']!=job['plan_id'] or published['state']!='complete':
                raise ValueError('落位清单与批次不符')
            self.validate_files(final,published)
            job=published
        elif action=='withdraw':
            if job['state'] not in ('complete','failed','prepared') or trash.exists():
                raise ValueError('批次不可撤回或恢复目录已存在')
            origin=final if final.exists() else staging
            if not origin.exists():
                raise ValueError('找不到批次目录')
            if job['state']=='complete':
                self.validate_files(origin,job)
            job.update(previous_state=job['state'],state='withdrawing',origin='exports' if origin==final else 'export_staging')
            write_json(journal,job)
            trash.parent.mkdir(parents=True,exist_ok=True);origin.rename(trash)
            job['state']='withdrawn'
        elif action=='restore':
            # Handle interruption immediately before/after the rename too.
            if job['state'] not in ('withdrawn','withdrawing') or job.get('previous_state')!='complete':
                raise ValueError('只有完整切片批次可恢复为完成')
            if trash.exists() and not final.exists():
                self.validate_files(trash,job);final.parent.mkdir(parents=True,exist_ok=True);trash.rename(final)
            elif final.exists() and not trash.exists():
                self.validate_files(final,job)
            else:
                raise ValueError('恢复路径冲突')
            job['state']='complete'
        else:
            raise ValueError('无效批次操作')
        write_json(journal,job)
        return job


    def list_batches(self):
        result=[]
        paths=sorted((self.root/'export_journals').glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:100]
        for p in paths:
            try:
                j=json.loads(p.read_text(encoding='utf-8'))
                result.append({'batch_id':j['batch_id'],'plan_id':j['plan_id'],'state':j['state'],
                               'files':len(j['files']),'created_at':j['created_at'],
                               'can_restore':j.get('previous_state')=='complete',
                               'can_retry':j['state'] in ('failed','retrying') or (j['state']=='withdrawn' and j.get('previous_state')=='failed')})
            except (OSError,ValueError,KeyError):
                continue
        return result
