import ast
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from patch_original_caption_sync import patch

FIXTURE = Path(__file__).parent / 'fixtures/original_caption_editor.txt'


def captions(monkeypatch):
    compliance = types.ModuleType('compliance')
    compliance.sanitize_text = lambda text: text.replace('禁用词', '提示音')
    monkeypatch.setitem(sys.modules, 'compliance', compliance)
    source = patch(FIXTURE.read_text())
    tree = ast.parse(source)
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    from types import SimpleNamespace
    namespace = dict(List=list, Seg=SimpleNamespace,
                     _make_ass_header=lambda p: '', _get_style_profile=lambda: None,
                     _dynamic_keywords=lambda cues: [], _kw_match=lambda *a: None,
                     _ANIM_STYLES=[''], _ANIM_KW='', _BORDER_TEXT='', _ASS_SUBTITLE_MARGIN=10,
                     _sec_to_ass=lambda t: f'{t:.2f}')
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<patched-captions>', 'exec'), namespace)
    return namespace['build_ass'], source


def seg(index, start, end, text, transition='cut:0'):
    return types.SimpleNamespace(idx=index, start=start, end=end, text=text,
                                 duration=end-start, transition=transition)


def test_original_cues_and_complete_text_survive_scene_merging(monkeypatch):
    build, source = captions(monkeypatch)
    selected = [seg(1, 20, 26, '这里只用于选段的合并文本')]
    cues = [seg(1, 20, 22, '第一句完整口播并且超过十四个字也需要保留全部内容'),
            seg(2, 22.2, 24, '第二句口播'), seg(3, 24, 26, '第三句口播')]
    ass = build(selected, cues, realistic=True)
    assert ass.count('Dialogue: 0,') == 3
    assert '0.00,2.00' in ass and '2.20,4.00' in ass and '4.00,6.00' in ass
    assert cues[0].text in ass.replace(r'\N', '')
    assert '这里只用于选段' not in ass
    assert source.count('source_segs if clip_engine in ("realistic", "conservative") else segs') == 2
    assert ':captions-v2:' in source and 'sha256(ass_content.encode' in source


def test_incoming_overlap_matches_audio_start_and_escapes_source(monkeypatch):
    build, _ = captions(monkeypatch)
    selected = [seg(1, 0, 4, 'a'), seg(2, 30, 34, 'b', 'fade:0.35'), seg(3, 50, 54, 'c')]
    cues = [seg(1, 0, 1, '第一句'), seg(2, 30, 31, r'路径\测试{原文}'), seg(3, 50, 51, '禁用词')]
    ass = build(selected, cues, realistic=True)
    assert '3.65,4.65' in ass and '7.65,8.65' in ass
    assert r'路径\\测试\{原文\}' in ass
    assert '禁用词' not in ass and '提示音' in ass
