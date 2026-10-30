"""Scoped production patch; preserves production-only matching and API policies."""
import ast
import re


def patch_source(source):
    tree = ast.parse(source)
    changes = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in {'load_group_context', 'score_product_match'}:
            continue
        old = ast.get_source_segment(source, node)
        new = old
        if node.name == 'load_group_context':
            assert 'srt_texts.append(f.read()[:8000])' in old, 'Unexpected subtitle loader'
            new, count = re.subn(r'(ORDER BY \{room_order\} id DESC)\s+LIMIT 30', r'\1', new)
            assert count == 1, 'Unexpected candidate query'
            start = new.index('    recordings_dir = ')
            end = new.index('    group_dict = dict(group)', start)
            new = new[:start] + '''    from media_contract import resolve_srt_file
    from qianchuan_product_evidence import load_transcripts
    srt_text, subtitle_audit = load_transcripts(
        [rec["filename"] for rec in recs], resolve_srt_file
    )

''' + new[end:]
            new = new.replace('"srt_text": "\\n".join(srt_texts),',
                              '"srt_text": srt_text,\n        "subtitle_audit": subtitle_audit,')
            assert 'srt_texts' not in new
        else:
            assert 'candidate_tokens' in old and 'exact_bonus' in old
            start = new.index('    corpus = " ".join([')
            new = new[:start] + '''    from qianchuan_product_evidence import product_evidence
    best = product_evidence(context, product_id=product_id, threshold=threshold)
    best["identity"] = context.get("identity")
    return best'''
        changes.append((node.lineno - 1, node.end_lineno, new + '\n'))
    assert len(changes) == 2
    lines = source.splitlines(keepends=True)
    for start, end, replacement in sorted(changes, reverse=True):
        lines[start:end] = [replacement]
    result = ''.join(lines)
    compile(result, 'qianchuan_matcher.py', 'exec')
    return result
