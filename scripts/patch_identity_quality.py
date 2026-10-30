"""Scoped production repair; never replace the divergent editor wholesale."""
import ast


def sample_source(srt_path: str, max_chars: int = 4000) -> str:
    """Keep intact, contiguous subtitle passages distributed over the source.

    These are explicit excerpts, not a continuous conversation or SKU evidence.
    Product retrieval must independently examine every original cue.
    """
    import re
    from pathlib import Path
    content = Path(srt_path).read_text(encoding='utf-8-sig')
    lines = [line.strip() for line in content.splitlines()
             if line.strip() and not re.match(r'^\d+$|^\d{2,3}:\d{2}:\d{2}', line.strip())]
    text = ' '.join(lines)
    if len(text) <= max_chars:
        return text
    if max_chars < 32:
        return ''
    # Whole cues, including adjacent context; never decimate individual characters.
    count = min(8, len(lines), max(1, max_chars // 160))
    separator = '\n[中间字幕省略，以下为另一时间段]\n'
    budget = max(1, (max_chars - (count-1)*len(separator)) // count)
    passages = []
    used = set()
    for k in range(count):
        anchor = round(k*(len(lines)-1)/max(1,count-1))
        indices = range(anchor, len(lines)) if k < count-1 else range(anchor, -1, -1)
        chosen = []
        size = 0
        for i in indices:
            if i in used or size + len(lines[i]) + bool(chosen) > budget:
                break
            chosen.append(i)
            size += len(lines[i]) + (len(chosen)>1)
        if chosen:
            used.update(chosen)
            passages.append(' '.join(lines[i] for i in sorted(chosen)))
    return separator.join(passages)


def replace_node(source, name, replacement):
    tree = ast.parse(source)
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    if len(nodes) != 1:
        raise ValueError('Unexpected function layout: '+name)
    node = nodes[0]
    lines = source.splitlines(keepends=True)
    lines[node.lineno-1:node.end_lineno] = [replacement+'\n']
    result = ''.join(lines)
    compile(result, '<quality-patch>', 'exec')
    return result


def patch_analyzer(source):
    import inspect
    source = source.replace('\r\n', '\n')
    old = ast.get_source_segment(source, next(n for n in ast.parse(source).body if getattr(n,'name',None)=='_srt_to_text'))
    if 'text[::max(1, step)]' not in old:
        raise ValueError('Sampling implementation changed; review first')
    replacement = inspect.getsource(sample_source).replace('def sample_source(', 'def _srt_to_text(', 1).rstrip()
    return replace_node(source, '_srt_to_text', replacement)


def patch_editor(source):
    source = source.replace('\r\n', '\n')
    node = next(n for n in ast.parse(source).body if getattr(n,'name',None)=='build_opening_hook')
    old = ast.get_source_segment(source, node)
    if old.count('    for s in segs:') != 1:
        raise ValueError('Opening candidate pool changed; review first')
    # selected can still contain an unverified identity; this prevents adding
    # NEW source regions, not a claim that existing selection is SKU-verified.
    updated = old.replace('    for s in segs:',
        '    # Never introduce another source window into the opening.\n'
        '    # Selection boundaries are authoritative, including exclusions/gaps.\n'
        '    for s in selected:', 1)
    return replace_node(source, 'build_opening_hook', updated)
