"""Preserve finished output during startup and deduplicate active clip admission."""
import ast
import inspect
from pathlib import Path
from prepare_2k_deploy import raw_replacements
from prepare_remote_audio_deploy import build as backup_runner

ROOT=Path(__file__).parents[1]


def change_function(source,name,change):
    node=next(n for n in ast.parse(source).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
    lines=source.splitlines(keepends=True)
    body=''.join(lines[node.lineno-1:node.end_lineno])
    lines[node.lineno-1:node.end_lineno]=change(body).splitlines(keepends=True)
    result=''.join(lines);compile(result,'<recovery-patch>','exec');return result


def patch_main(source):
    def helper(body):
        old='    return bool(path and os.path.exists(path))'
        if body.count(old)!=1:raise RuntimeError('Media existence helper drift')
        return body.replace(old,'''    if path and os.path.exists(path):
        return True
    legacy = os.path.join(os.path.dirname(__file__), "..", "recordings", filename) if filename else None
    return bool(legacy and os.path.exists(legacy))''')
    def recovery(body):
        old='''            if not os.path.exists(os.path.join(recordings_dir, r["clip_filename"]))
            and os.path.exists(os.path.join(recordings_dir, r["filename"]))'''
        if body.count(old)!=1:raise RuntimeError('Startup recovery drift')
        return body.replace(old,'''            if not _recording_file_exists(r["clip_filename"])
            and _recording_file_exists(r["filename"])''')
    return change_function(change_function(source,'_recording_file_exists',helper),'_reset_stuck_clip_tasks',recovery)


def patch_transcribe(source):
    if '_enqueuing_ids' in source or 'async def _enqueue_editor(' in source:
        raise RuntimeError('Admission wrapper already exists; inspect first')
    def admission(body):
        if body.count('async def _run_editor(')!=1:raise RuntimeError('Editor entrypoint drift')
        return WRAPPER+body.replace('async def _run_editor(', 'async def _enqueue_editor(',1)
    def dispatch(body):
        old='if recording_id in _paused_ids:'
        if body.count(old)!=1:raise RuntimeError('Dispatcher drift')
        return body.replace(old,'if recording_id in _paused_ids or recording_id in _running_ids:')
    return change_function(change_function(source,'_run_editor',admission),'_try_dispatch',dispatch)


def build():
    transcribe=(ROOT/'backend/transcribe.py').read_text()
    wrapper=transcribe[transcribe.index('_enqueuing_ids: set = set()'):transcribe.index('async def _enqueue_editor(')]
    definitions='\n\n'.join(inspect.getsource(f) for f in [raw_replacements,change_function,patch_main,patch_transcribe])
    setup='from pathlib import Path\nimport ast,difflib\nWRAPPER='+repr(wrapper)+'\n'+definitions+'''
PLAN=[]
for filename,patch in [
 (r'C:\\Users\\neo\\douyin_backend\\backend\\main.py',patch_main),
 (r'C:\\Users\\neo\\douyin_backend\\backend\\transcribe.py',patch_transcribe),
]:
 source=Path(filename).read_bytes().decode('utf-8')
 patched=patch(source.replace('\\r\\n','\\n'))
 PLAN.append((filename,raw_replacements(source,patched)))
'''
    body=backup_runner().split('\n',1)[1].replace("'remote-audio-'", "'clip-recovery-'")
    body=body.replace("old=old.replace('\\n',newline);new=new.replace('\\n',newline)",'pass')
    return setup+body


if __name__=='__main__':
    print(build())
