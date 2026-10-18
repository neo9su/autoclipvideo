"""CPU-only final-export regression fixtures; no shared GPU work."""
import ast
import asyncio
import importlib.util
import json
import logging
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import prepare_2k_deploy as patch


def constants():
    tree = ast.parse((ROOT / 'gpu_service/main.py').read_text())
    names = {'CLIP_W','CLIP_H','PUBLISH_W','PUBLISH_H','PUBLISH_SCALE'}
    nodes = [n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in n.targets)]
    env = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<export-constants>', 'exec'), env)
    return env


def node(name):
    tree = ast.parse((ROOT / 'gpu_service/main.py').read_text())
    return next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)


def test_working_resolution_remains_1080p_but_export_is_2k():
    env = constants()
    assert (env['CLIP_W'], env['CLIP_H']) == (1080,1920)
    assert (env['PUBLISH_W'], env['PUBLISH_H']) == (1440,2560)


@pytest.mark.parametrize('method', ['_do_clip_job','_do_director_job'])
@pytest.mark.parametrize('has_subs', [False,True])
def test_final_scale_applies_before_subtitles_or_without_subtitles(method, has_subs):
    branches = [n for n in ast.walk(node(method)) if isinstance(n, ast.If)
                and isinstance(n.test, ast.Name) and n.test.id == 'has_subs'
                and 'video_filter' in ast.unparse(n)]
    assert len(branches) == 1
    env = constants() | dict(has_subs=has_subs, ass_path='C:/test/subs.ass', FONTS_DIR='',
                            subtitle_fonts_dir='', audio_filter='[0:a]anull[aout]')
    exec(compile(ast.Module(body=branches, type_ignores=[]), '<actual-final-filter>', 'exec'), env)
    graph = env['filter_complex']
    assert 'scale=1440:2560' in graph
    assert '[vout]' in graph
    if has_subs:
        assert graph.index('scale=1440:2560') < graph.index('ass=filename')


async def create_input(path):
    p = await asyncio.create_subprocess_exec('ffmpeg','-v','error','-y',
        '-f','lavfi','-i','color=blue:size=180x320:rate=25:duration=0.24',
        '-f','lavfi','-i','sine=frequency=440:duration=0.24',
        '-c:v','libx264','-preset','ultrafast','-c:a','aac',str(path),
        stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    _,error = await p.communicate(); assert p.returncode == 0,error.decode()


async def cpu_ffmpeg(*args):
    args = list(args)
    # Exercise the worker's actual command, substituting a local CPU encoder.
    if 'h264_nvenc' in args:
        args[args.index('h264_nvenc')] = 'libx264'
        args[-1:-1] = ['-preset','ultrafast']
    p = await asyncio.create_subprocess_exec(*args,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    _,error = await p.communicate()
    assert p.returncode == 0,error.decode()[-2000:]
    return p.returncode


def probe(path):
    r = subprocess.run(['ffprobe','-v','error','-show_streams','-of','json',str(path)],capture_output=True,check=True)
    streams=json.loads(r.stdout)['streams']
    video=next(s for s in streams if s['codec_type']=='video')
    assert (video['width'],video['height']) == (1440,2560)
    assert video['codec_name']=='h264'
    assert any(s['codec_type']=='audio' for s in streams)


@pytest.mark.asyncio
@pytest.mark.parametrize('method,count', [('_do_classic_concat_job',1),('_do_classic_concat_job',2),('_do_concat_job',2)])
async def test_actual_concat_exports_2k_and_preserves_source(tmp_path, method, count):
    inputs=[tmp_path/f'input{i}.mp4' for i in range(count)]
    for p in inputs: await create_input(p)
    classic={'job':{'status':'queued'}}; concat={'job':{'status':'queued'}}
    clips={str(i):{'status':'done','output_path':str(p)} for i,p in enumerate(inputs)}
    env=constants() | dict(os=os,STORAGE_DIR=str(tmp_path),_run_ffmpeg=cpu_ffmpeg,
                          _classic_concat_jobs=classic,_concat_jobs=concat,_clip_jobs=clips,
                          _db_update_concat_job=lambda *args,**kw:None,logger=logging.getLogger('test'))
    exec(compile(ast.Module(body=[node(method)],type_ignores=[]),'<actual-concat>','exec'),env)
    await env[method]('job',[str(p) for p in inputs] if 'classic' in method else list(clips))
    result=classic['job'] if 'classic' in method else concat['job']
    assert result['status']=='done',result
    probe(result['output_path'])
    assert all(p.exists() for p in inputs)


@pytest.mark.asyncio
async def test_no_subtitle_final_filter_renders_2k(tmp_path):
    source=tmp_path/'input.mp4';out=tmp_path/'final.mp4';await create_input(source)
    branch=next(n for n in ast.walk(node('_do_clip_job')) if isinstance(n,ast.If)
                and isinstance(n.test,ast.Name) and n.test.id=='has_subs' and 'video_filter' in ast.unparse(n))
    env=constants()|dict(has_subs=False,audio_filter='[0:a]anull[aout]')
    exec(compile(ast.Module(body=[branch],type_ignores=[]),'<clip-filter>','exec'),env)
    await cpu_ffmpeg('ffmpeg','-v','error','-y','-i',str(source),'-filter_complex',env['filter_complex'],
                    '-map',env['vmap'],'-map',env['amap'],'-c:v','h264_nvenc','-pix_fmt','yuv420p','-c:a','aac',str(out))
    probe(out)


def test_production_migration_preserves_working_frames_and_explicit_options():
    # The deployed director supports explicit output specs absent from the repository baseline.
    old=subprocess.check_output(['git','show','2debb7e:gpu_service/main.py'],cwd=ROOT,text=True)
    old=old.replace('pad=1080:1920:(ow-iw)/2:(oh-ih)/2",','pad=1080:1920:(ow-iw)/2:(oh-ih)/2,fps=25",')
    n=next(n for n in ast.parse(old).body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_do_director_job')
    lines=old.splitlines(keepends=True)
    # A harmless source-only stand-in for the deployed director's resolution initialization.
    lines.insert(n.body[0].lineno-1,'    resolution = str(output_spec.get("resolution") or "1080x1920")\n')
    source=''.join(lines)
    result=patch.patch_gpu(source)
    assert 'CLIP_W    = 1080' in result and 'CLIP_H    = 1920' in result
    assert 'output_spec.get("resolution") or "1440x2560"' in result
    assert 'PUBLISH_SCALE + ",fps=25"' in result
    with pytest.raises(RuntimeError): patch.patch_gpu(result)


def test_mixed_line_endings_are_preserved_outside_replacements():
    original = 'alpha=1\r\nbeta=2\ngamma=3\r\n'
    patched = 'alpha=1\nbeta=20\ngamma=3\n'
    result = original
    for old,new in patch.raw_replacements(original,patched):
        assert result.count(old)==1
        result=result.replace(old,new)
    assert result.replace('\r\n','\n')==patched
    assert result.startswith('alpha=1\r\n') and result.endswith('gamma=3\r\n')


def test_generated_deployer_does_not_double_normalize_raw_pairs():
    script=patch.build()
    assert "old=old.replace('\\n',newline)" not in script
    compile(script,'<prepared-2k>','exec')
