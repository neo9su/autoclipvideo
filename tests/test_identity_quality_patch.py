import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import asyncio
import sys

spec=importlib.util.spec_from_file_location('quality_patch',Path(__file__).parents[1]/'scripts/patch_identity_quality.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def test_sampler_preserves_whole_cues_and_budget(tmp_path):
    lines=[f'这是琥珀精灵第{i}句话完整展示发际线。' for i in range(800)]
    p=tmp_path/'source.srt'
    p.write_text('\n\n'.join(f'{i+1}\n00:00:01,000 --> 00:00:02,000\n{x}' for i,x in enumerate(lines)),encoding='utf-8-sig')
    result=m.sample_source(p,4000)
    assert len(result)<=4000
    assert lines[0] in result and lines[-1] in result
    assert '琥珀精灵' in result
    for excerpt in result.split('\n[中间字幕省略，以下为另一时间段]\n'):
        assert all(cue in lines for cue in excerpt.split(' '))


def test_short_source_unchanged(tmp_path):
    p=tmp_path/'x.srt';p.write_text('1\n00:00:00,000 --> 00:00:01,000\n这款叫天蝎座\n',encoding='utf-8')
    assert m.sample_source(p)=='这款叫天蝎座'


def test_patch_refuses_unknown_sampler():
    import pytest
    with pytest.raises(ValueError):m.patch_analyzer('def _srt_to_text(x):\n return x\n')


def test_hook_uses_selected_windows_only():
    source='async def build_opening_hook(segs, selected):\n    output=[]\n    for s in segs:\n        output.append((s.start,s.end))\n    return output\n'
    ns={};exec(m.patch_editor(source),ns)
    selected=[SimpleNamespace(start=10,end=15),SimpleNamespace(start=30,end=35)]
    all_segs=[SimpleNamespace(start=0,end=100)]
    assert asyncio.run(ns['build_opening_hook'](all_segs,selected))==[(10,15),(30,35)]
    assert asyncio.run(ns['build_opening_hook'](all_segs,[]))==[]
