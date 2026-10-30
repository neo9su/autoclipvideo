"""Use configured storage for API clip downloads, with legacy-directory fallback."""
from prepare_remote_audio_deploy import build as backup_runner


def build():
    replacements=[]
    for variable in ['rec','clip']:
        old=f'    clip_path = os.path.join(os.path.dirname(__file__), "..", "recordings", {variable}["clip_filename"])'
        new=f'    clip_path = _recording_file_path({variable}["clip_filename"])\n    if not clip_path or not os.path.isfile(clip_path):\n    '+old
        replacements.append((old,new))
    plan=[(r'C:\Users\neo\douyin_backend\backend\main.py',replacements)]
    preflight='''from pathlib import Path
source=Path(r'C:\\Users\\neo\\douyin_backend\\backend\\main.py').read_text(encoding='utf-8')
assert 'def _recording_file_path(' in source, 'Existing media helper required'
assert '_recording_file_path(clip["clip_filename"])' not in source, 'Inspect already-patched source'
'''
    body=backup_runner().split('\n',1)[1].replace("'remote-audio-'", "'clip-download-storage-'")
    return preflight+'PLAN = '+repr(plan)+'\n'+body


if __name__=='__main__':
    print(build())
