"""Build a drift-checked Windows deployment script; does not restart services."""
import ast
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).parents[1]
BASELINE = '90da097'


def function_text(source, name):
    node = next(n for n in ast.walk(ast.parse(source))
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    return '\n'.join(source.splitlines()[node.lineno - 1:node.end_lineno])


def build():
    old_voice = subprocess.check_output(['git', 'show', BASELINE + ':backend/voice_director.py'], cwd=ROOT, text=True)
    old_gpu = subprocess.check_output(['git', 'show', BASELINE + ':gpu_service/main.py'], cwd=ROOT, text=True)
    voice = (ROOT / 'backend/voice_director.py').read_text()
    gpu = (ROOT / 'gpu_service/main.py').read_text()
    marker = '        # ─────────────────────────────────────────────────────────────────────'
    start_old = old_voice.index('            async with local_media_slot("voice director audio stretch"):')
    end_old = old_voice.index(marker, start_old)
    start_new = voice.index('            stretched = await self._merge_audio_segments(')
    end_new = voice.index(marker, start_new)
    voice_replacements = [
        (function_text(old_voice, '_merge_audio_segments'), function_text(voice, '_merge_audio_segments')),
        (old_voice[start_old:end_old], voice[start_new:end_new]),
        ('            stretched_path = merged + "_stretched.wav"\n', ''),
        ('from local_media_guard import local_media_slot\n', ''),
    ]
    health_helper = function_text(gpu, '_active_media_job_counts')
    gpu_replacements = [
        (function_text(old_gpu, name), function_text(gpu, name))
        for name in ['_run_audio_concat_job', 'create_audio_concat_job']
    ] + [
        ('@app.get("/health")', health_helper + '\n\n\n@app.get("/health")'),
        ('        "clip_jobs_pending": clip_pending,', '        "clip_jobs_pending": clip_pending,\n        "media_jobs_active": _active_media_job_counts(),'),
    ]
    plan = [
        (r'C:\Users\neo\douyin_backend\backend\voice_director.py', voice_replacements),
        (r'C:\Users\neo\douyin_processor\gpu_service\main.py', gpu_replacements),
        (r'C:\Users\neo\douyin_backend\gpu_service\main.py', gpu_replacements),
    ]
    return 'PLAN = ' + repr(plan) + '\n' + r'''
from pathlib import Path
import datetime,hashlib,json,os
changes=[]
for filename,replacements in PLAN:
    p=Path(filename);original=p.read_bytes();text=original.decode('utf-8')
    newline='\r\n' if '\r\n' in text else '\n'
    for old,new in replacements:
        old=old.replace('\n',newline);new=new.replace('\n',newline)
        if text.count(old)!=1:raise RuntimeError('Source preflight failed: '+filename)
        text=text.replace(old,new)
    compile(text,filename,'exec')
    changes.append((p,original,text.encode('utf-8')))
backup=Path(r'C:\Users\neo\douyin_backend\codex_rollbacks')/('remote-audio-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
backup.mkdir()
manifest=[]
for i,(p,old,new) in enumerate(changes):
    name=str(i)+'.before';(backup/name).write_bytes(old)
    manifest.append(dict(target=str(p),backup=name,before=hashlib.sha256(old).hexdigest(),after=hashlib.sha256(new).hexdigest()))
(backup/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
rollback="""from pathlib import Path
import json,hashlib,os
b=Path(__file__).parent
items=json.loads((b/'manifest.json').read_text())
for m in items:
 p=Path(m['target'])
 assert hashlib.sha256(p.read_bytes()).hexdigest() in (m['before'],m['after']), 'Source drift; no rollback'
 assert hashlib.sha256((b/m['backup']).read_bytes()).hexdigest()==m['before']
for m in items:
 p=Path(m['target']);t=p.with_suffix('.rollback.tmp')
 t.write_bytes((b/m['backup']).read_bytes());os.replace(t,p)
print('Code restored; restart backend and GPU only when idle. No database changed.')
"""
(backup/'rollback.py').write_text(rollback,encoding='utf-8')
for p,old,new in changes:
 if p.read_bytes()!=old:raise RuntimeError('Source changed during backup')
for p,old,new in changes:
 t=p.with_suffix('.codex.tmp');t.write_bytes(new);os.replace(t,p)
print(json.dumps(dict(backup=str(backup),files=manifest,restart_required=True)))
'''


if __name__ == '__main__':
    print(build())
