"""Small synthetic CPU fixtures, no production media or GPU requests."""
import ast
import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).parents[1]


def audio_filter(vf, d1, d2, fade):
    tree = ast.parse((ROOT / 'gpu_service/main.py').read_text())
    func = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_nvenc_xfade_merge')
    assignment = next(n for n in ast.walk(func) if isinstance(n, ast.Assign)
                      and 'acrossfade=' in ast.unparse(n.value))
    return eval(compile(ast.Expression(assignment.value), '<actual-filter>', 'eval'),
                dict(vf=vf, d1=d1, d2=d2, fade=fade))


def run(*args):
    return subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', *map(str, args)], capture_output=True)


def make_clip(path, video_duration, audio_duration):
    result = run('-f', 'lavfi', '-i', f'color=c=blue:s=320x180:r=25:d={video_duration}',
                 '-f', 'lavfi', '-i', f'sine=frequency=440:sample_rate=48000:duration={audio_duration}',
                 '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', path)
    assert result.returncode == 0, result.stderr.decode()


def durations(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(path)], capture_output=True, check=True)
    return {s['codec_type']: float(s['duration']) for s in json.loads(result.stdout)['streams']}


def merge(first, second, output, d1, d2, fade=0.35):
    vf = (f'[0:v]settb=1/25[va];[1:v]settb=1/25[vb];'
          f'[va][vb]xfade=transition=slideleft:duration={fade}:offset={d1-fade:.3f}[vout]')
    result = run('-i', first, '-i', second, '-filter_complex', audio_filter(vf, d1, d2, fade),
                 '-map', '[vout]', '-map', '[aout]', '-c:v', 'libx264', '-preset', 'ultrafast',
                 '-pix_fmt', 'yuv420p', '-c:a', 'aac', output)
    assert result.returncode == 0, result.stderr.decode()


def test_production_legacy_boolean_offset_reproduces_failure():
    result = run('-f', 'lavfi', '-i', 'sine=duration=2', '-f', 'lavfi', '-i', 'sine=duration=1',
                 '-filter_complex', '[0:a][1:a]acrossfade=d=0.35:o=1.650[a]', '-map', '[a]', '-f', 'null', '-')
    assert result.returncode != 0
    assert b'boolean' in result.stderr and b'1.650' in result.stderr


@pytest.mark.parametrize('first_audio,second_audio', [(1.5, 1.8), (2.5, 0.8)])
def test_short_and_long_audio_stay_on_video_timeline(tmp_path, first_audio, second_audio):
    first, second, output = [tmp_path / name for name in ['a.mp4', 'b.mp4', 'out.mp4']]
    make_clip(first, 2, first_audio); make_clip(second, 1.2, second_audio)
    merge(first, second, output, 2, 1.2)
    times = durations(output)
    assert times['audio'] == pytest.approx(2.85, abs=0.08)
    assert times['video'] == pytest.approx(2.85, abs=0.08)
    assert abs(times['video'] - times['audio']) < 0.08


def test_three_clip_merge_does_not_accumulate_audio_padding(tmp_path):
    a, b, c, pair, final = [tmp_path / name for name in ['a.mp4','b.mp4','c.mp4','pair.mp4','final.mp4']]
    make_clip(a, 2, 1.5); make_clip(b, 1.2, 1.8); make_clip(c, 1.2, 0.8)
    merge(a, b, pair, 2, 1.2)
    merge(pair, c, final, 2.85, 1.2)
    times = durations(final)
    assert times['audio'] == pytest.approx(3.7, abs=0.08)
    assert times['video'] == pytest.approx(3.7, abs=0.08)
    assert abs(times['video'] - times['audio']) < 0.08
