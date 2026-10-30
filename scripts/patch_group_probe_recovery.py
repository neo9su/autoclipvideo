"""Apply anchored lifecycle/probe fixes while retaining deployment-specific code."""
import ast

def patch_analyzer(source):
    tree=ast.parse(source)
    node=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_get_or_create_group')
    lines=source.splitlines(keepends=True);body=''.join(lines[node.lineno-1:node.end_lineno])
    if 'OPEN_GROUP_SQL' in body:raise ValueError('Already patched')
    if body.count('WHERE room_id = ?') not in (1,2):raise ValueError('Group query drift')
    # The interpolation is a fixed internal SQL predicate, never user input.
    body=body.replace('WHERE room_id = ?', 'WHERE ({OPEN_GROUP_SQL}) AND room_id = ?')
    body=body.replace('"""SELECT', 'f"""SELECT').replace('"SELECT id, wig_model, wig_color, label, product_keywords FROM clip_groups WHERE', 'f"SELECT id, wig_model, wig_color, label, product_keywords FROM clip_groups WHERE')
    # Find the first statement, since deployed signatures span multiple lines.
    first=node.body[0].lineno-node.lineno
    parts=body.splitlines(keepends=True);parts.insert(first,'    from group_lifecycle import OPEN_GROUP_SQL\n');body=''.join(parts)
    result=''.join(lines[:node.lineno-1])+body+'\n'+''.join(lines[node.end_lineno:]);ast.parse(result);return result

def patch_transcribe(source):
    tree=ast.parse(source);node=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_validate_mp4')
    if 'from media_probe import' in source:raise ValueError('Already patched')
    lines=source.splitlines(keepends=True)
    replacement='async def _validate_mp4(filepath: str) -> tuple[bool, str]:\n    from media_probe import validate_mp4\n    return await validate_mp4(filepath)\n'
    source=''.join(lines[:node.lineno-1])+replacement+''.join(lines[node.end_lineno:])
    marker='                    if not valid:\n'
    # Guard each validation failure block without changing unrelated editor checks.
    anchor='valid, err_msg = await _validate_mp4(upload_path)\n'+marker
    count=source.count(anchor)
    if count not in (1,2):raise ValueError('Probe caller drift')
    source=source.replace(anchor,'valid, err_msg = await _validate_mp4(upload_path)\n'+marker+'''                        if err_msg.startswith('media probe pending:'):
                            logger.warning("Deferring media check for %s: %s", primary_id, err_msg)
                            continue
''')
    ast.parse(source);return source
