"""Move network-file checks off the API loop and serialize duplicate full-list reads."""
import ast


def patch(source):
    node=next(n for n in ast.parse(source).body if isinstance(n,ast.AsyncFunctionDef) and n.name=='list_groups')
    lines=source.splitlines(keepends=True)
    old=''.join(lines[node.lineno-1:node.end_lineno]).rstrip('\n')
    if '_list_groups_snapshot' in source:raise ValueError('Already patched')
    result_lines=[line for line in old.splitlines() if line.startswith('    result = [dict(r) | _artifact_statuses(dict(r))')]
    if len(result_lines)!=1:raise ValueError('Group result anchor drift')
    traits=' | _hair_traits(dict(r))' in result_lines[0]
    if result_lines[0] not in ['    result = [dict(r) | _artifact_statuses(dict(r)) for r in rows]', '    result = [dict(r) | _artifact_statuses(dict(r)) | _hair_traits(dict(r)) for r in rows]']:
        raise ValueError('Unexpected group metadata format')
    collect='''    def collect_groups():
        from group_artifact_snapshot import GroupArtifactSnapshot
        versions = {'classic': 'merged_filename', 'director': 'director_final_video',
                    'realistic': 'realistic_final_video', 'conservative': 'conservative_final_video',
                    'creative': 'creative_final_video', 'qianchuan': 'qianchuan_final_video',
                    'codex': 'codex_final_video'}
        items = [dict(row) for row in rows]
        inventory = GroupArtifactSnapshot(versions, values=(item.get(field) for item in items for field in versions.values()))
        for item in items:
            for version, field in versions.items():
                path, reason = inventory.resolve(item.get(field), version)
                item[version + '_available'] = bool(path)
                item[version + '_file_status'] = 'ready' if path else reason
'''
    if traits:collect+='            item.update(_hair_traits(item))\n'
    collect+='        return items\n    result = await asyncio.to_thread(collect_groups)'
    new=old.replace('async def list_groups():','async def _list_groups_snapshot():',1).replace(result_lines[0],collect,1)
    anchor='    _groups_cache = (now, result)'
    if new.count(anchor)!=1:raise ValueError('Group cache anchor drift')
    new=new.replace(anchor,'    _groups_cache = (time.monotonic(), result)',1)
    wrapper='''async def list_groups():
    async with _groups_list_lock:
        return await _list_groups_snapshot()


'''
    result=source.replace(old,wrapper+new,1)
    anchor='@app.get("/api/groups")'
    if result.count(anchor)!=1:raise ValueError('Group route anchor drift')
    result=result.replace(anchor,'_groups_list_lock = asyncio.Lock()\n\n'+anchor,1)
    compile(result,'<groups event-loop patch>','exec')
    return result
