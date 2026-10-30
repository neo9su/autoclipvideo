"""Patch known final-export paths; preserve lower-resolution working frames."""
import ast
import difflib
import re
from pathlib import Path
from prepare_remote_audio_deploy import build as backup_runner

DECLARATIONS = '''
# Keep intermediate frames light; publish at vertical 2K in the final encode.
PUBLISH_W = 1440
PUBLISH_H = 2560
PUBLISH_SCALE = (
    f"scale={PUBLISH_W}:{PUBLISH_H}:force_original_aspect_ratio=decrease:flags=lanczos,"
    f"pad={PUBLISH_W}:{PUBLISH_H}:(ow-iw)/2:(oh-ih)/2"
)'''


def replace(source, old, new, count=1):
    if source.count(old) != count:
        raise RuntimeError('Export source drift: ' + old[:70])
    return source.replace(old, new)


def recode_concat(body):
    pattern = r'(?m)^(\s*)"-c", "copy",$'
    def replacement(match):
        indent = match[1]
        return '\n'.join(indent + line for line in [
            '"-vf", PUBLISH_SCALE + ",fps=25",', '"-pix_fmt", "yuv420p",',
            '"-c:v", "h264_nvenc", "-b:v", "10M",', '"-c:a", "copy",',
        ])
    patched, count = re.subn(pattern, replacement, body)
    if count != 1:
        raise RuntimeError('Expected one final concat copy operation')
    return patched


def patch_gpu(source):
    if 'PUBLISH_W =' in source:
        raise RuntimeError('Publish constants already exist; inspect before reapplying')
    text = replace(source, 'CLIP_H    = 1920', 'CLIP_H    = 1920' + DECLARATIONS)
    lines = text.splitlines(keepends=True)
    targets = {'_do_clip_job', '_do_director_job', '_do_concat_job', '_do_classic_concat_job'}
    nodes = [n for n in ast.parse(text).body if isinstance(n, ast.AsyncFunctionDef) and n.name in targets]
    if {n.name for n in nodes} != targets:
        raise RuntimeError('Export methods missing')
    for node in sorted(nodes, key=lambda n: n.lineno, reverse=True):
        body = ''.join(lines[node.lineno - 1:node.end_lineno])
        if node.name == '_do_clip_job':
            body = replace(body, 'f"[0:v]ass=filename=', 'f"[0:v]{PUBLISH_SCALE},ass=filename=', 2)
            body = replace(body, '''            filter_complex = audio_filter
            vmap, amap = "0:v", "[aout]"''', '''            filter_complex = f"{audio_filter};[0:v]{PUBLISH_SCALE},format=yuv420p[vout]"
            vmap, amap = "[vout]", "[aout]"''')
        elif node.name == '_do_director_job':
            body = replace(body, 'resolution = str(output_spec.get("resolution") or "1080x1920")',
                           'resolution = str(output_spec.get("resolution") or "1440x2560")')
        elif node.name == '_do_classic_concat_job':
            old = '"-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,fps=25",'
            if body.count(old) != 2:
                raise RuntimeError('Unexpected classic concat normalization')
            body = body.replace(old, '"-vf", PUBLISH_SCALE + ",fps=25",', 1)
            body = recode_concat(body)
        else:
            body = recode_concat(body)
        lines[node.lineno - 1:node.end_lineno] = body.splitlines(keepends=True)
    result = ''.join(lines)
    compile(result, 'gpu_service/main.py', 'exec')
    return result


def patch_editor(source):
    text = replace(source, 'OUT_W = 1080', 'OUT_W = 1440')
    text = replace(text, 'OUT_H = 1920', 'OUT_H = 2560')
    text = replace(text, 'scale=1080:1920:force_original_aspect_ratio=decrease:flags=lanczos,',
                   'scale=1440:2560:force_original_aspect_ratio=decrease:flags=lanczos,')
    text = replace(text, 'pad=1080:1920:(ow-iw)/2:(oh-ih)/2,', 'pad=1440:2560:(ow-iw)/2:(oh-ih)/2,')
    compile(text, 'editor.py', 'exec')
    return text


def raw_replacements(original, patched):
    """Retain mixed line endings in untouched code and matching context."""
    raw_lines = original.splitlines(keepends=True)
    old_lines = original.replace('\r\n', '\n').splitlines(keepends=True)
    new_lines = patched.splitlines(keepends=True)
    pairs = []
    for group in difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False).get_grouped_opcodes(3):
        start, end = group[0][1], group[-1][2]
        newline = '\r\n' if any(line.endswith('\r\n') for line in raw_lines[start:end]) else '\n'
        output = []
        for tag, i1, i2, j1, j2 in group:
            if tag == 'equal':
                output.extend(raw_lines[i1:i2])
            else:
                output.extend(line.replace('\n', newline) for line in new_lines[j1:j2])
        pairs.append((''.join(raw_lines[start:end]), ''.join(output)))
    return pairs


def build():
    # Execute the pure patch functions on Windows; do not transfer large production sources.
    here = Path(__file__).read_text()
    definitions = here[here.index('DECLARATIONS = '):here.index('\ndef build():')]
    setup = '''from pathlib import Path
import ast,re,difflib
''' + definitions + '''
PLAN=[]
for filename,patch in [
 (r'C:\\Users\\neo\\douyin_processor\\gpu_service\\main.py',patch_gpu),
 (r'C:\\Users\\neo\\douyin_backend\\gpu_service\\main.py',patch_gpu),
 (r'C:\\Users\\neo\\douyin_backend\\backend\\editor.py',patch_editor),
]:
 source=Path(filename).read_bytes().decode('utf-8')
 patched=patch(source.replace('\\r\\n','\\n'))
 PLAN.append((filename,raw_replacements(source,patched)))
'''
    body = backup_runner().split('\n', 1)[1].replace("'remote-audio-'", "'publish-2k-'")
    # Replacement pairs are already byte-faithful; do not normalize them again.
    body = body.replace("old=old.replace('\\n',newline);new=new.replace('\\n',newline)", 'pass')
    return setup + body


if __name__ == '__main__':
    print(build())
