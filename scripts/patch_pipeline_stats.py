"""Exclude deliberately removed source media from executable queue counters."""
import ast

def patch(source):
    node=next(n for n in ast.parse(source).body if isinstance(n,ast.AsyncFunctionDef) and n.name=='get_stats')
    lines=source.splitlines(keepends=True)
    body=''.join(lines[node.lineno-1:node.end_lineno])
    old='transcribed = 2 AND clipped = 0 THEN'
    new='transcribed = 2 AND clipped = 0 AND local_deleted = 0 AND end_time IS NOT NULL THEN'
    if body.count(old)!=1:raise RuntimeError('Queue statistics source drift')
    lines[node.lineno-1:node.end_lineno]=body.replace(old,new,1).splitlines(keepends=True)
    result=''.join(lines);compile(result,'main.py','exec');return result
