"""Copy only the two selection functions into a drift-checked production file."""
import ast
from pathlib import Path


def patch(source):
    if 'Preserve the task\'s chosen artifact' in source:
        raise ValueError('Selection patch already applied')
    if 'values.append(video_path)' not in source:
        raise ValueError('Old selection implementation drifted')
    canonical=(Path(__file__).parents[1]/'backend/video_path_resolver.py').read_text()
    names={'resolve_publish_video','resolve_video_path'}
    replacements={n.name:ast.get_source_segment(canonical,n) for n in ast.parse(canonical).body if isinstance(n,ast.FunctionDef) and n.name in names}
    nodes=[n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name in names]
    if len(nodes)!=2:raise ValueError('Selection functions drifted')
    lines=source.splitlines(keepends=True)
    for node in reversed(nodes):lines[node.lineno-1:node.end_lineno]=[replacements[node.name]+'\n']
    result=''.join(lines);compile(result,'video_path_resolver.py','exec');return result
