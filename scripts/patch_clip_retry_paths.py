"""Patch only three retry handlers; leave existing media execution code untouched."""
import ast

def replace(source,name,fn):
    node=next(n for n in ast.parse(source).body if isinstance(n,ast.AsyncFunctionDef) and n.name==name)
    lines=source.splitlines(keepends=True);body=''.join(lines[node.lineno-1:node.end_lineno]);new=fn(body)
    lines[node.lineno-1:node.end_lineno]=new.splitlines(keepends=True);return ''.join(lines)

IMPORTS='''    from recording_paths import resolve_recording_path
    from clip_retry_sources import resolve_retry_files
'''
def patch(source):
    def general(body):
        start=body.index('    mp4_path = os.path.join(')
        end=body.index('    clip_count =',start)
        return body[:start]+IMPORTS+'''    if rec["local_deleted"] or rec["clipped"] == 1:
        raise HTTPException(status_code=409, detail="录像已移除或任务正在运行")
    mp4_path, srt_path, error = await asyncio.to_thread(
        resolve_retry_files, rec["filename"], resolve_recording_path, resolve_srt_path)
    if error:
        raise HTTPException(status_code=404, detail=error)
'''+body[end:]
    def single(body):
        start=body.index('    mp4_path = os.path.join(');end=body.index('    # Reset failed state',start)
        body=body[:start]+IMPORTS+'''    if rec["local_deleted"] or rec["transcribed"] != 2:
        raise HTTPException(status_code=409, detail="源文件已移除或转写尚未完成")
    mp4_path, srt_path, error = await asyncio.to_thread(
        resolve_retry_files, rec["filename"], resolve_recording_path, resolve_srt_path)
    if error:
        raise HTTPException(status_code=404, detail=error)

'''+body[end:]
        old='await db.execute("UPDATE recordings SET clipped = 0, clip_error = NULL WHERE id = ?", (recording_id,))'
        if body.count(old)!=1:raise RuntimeError('Single retry claim drift')
        body=body.replace(old,'cursor = await db.execute("UPDATE recordings SET clipped = 0, clip_error = NULL WHERE id = ? AND clipped = -1 AND local_deleted = 0 AND transcribed = 2", (recording_id,))',1)
        marker='    asyncio.create_task(_run_editor('
        return body.replace(marker,'    if cursor.rowcount != 1:\n        raise HTTPException(status_code=409, detail="任务已被其他请求领取，请刷新查看")\n\n'+marker,1)
    def bulk(body):
        body=body.replace('    base = RECORDINGS_DIR\n',IMPORTS,1)
        body=body.replace('if not rec or rec["skip_reason"]:', 'if not rec or rec["skip_reason"] or rec["local_deleted"] or rec["transcribed"] != 2:',1)
        start=body.index('        mp4_path = os.path.join(');end=body.index('        async with aio_connect() as db:',start)
        body=body[:start]+'''        mp4_path, srt_path, error = await asyncio.to_thread(
            resolve_retry_files, rec["filename"], resolve_recording_path, resolve_srt_path)
        if error:
            skipped.append(recording_id)
            continue
'''+body[end:]
        old='await db.execute("UPDATE recordings SET clipped = 0, clip_error = NULL WHERE id = ?", (recording_id,))'
        if body.count(old)!=1:raise RuntimeError('Bulk retry claim drift')
        body=body.replace(old,'cursor = await db.execute("UPDATE recordings SET clipped = 0, clip_error = NULL WHERE id = ? AND clipped = -1 AND local_deleted = 0 AND transcribed = 2", (recording_id,))',1)
        marker='        asyncio.create_task(_run_editor('
        return body.replace(marker,'        if cursor.rowcount != 1:\n            skipped.append(recording_id)\n            continue\n'+marker,1)
    if 'from clip_retry_sources import' in source:raise RuntimeError('Already patched; inspect source')
    for name,fn in [('retry_clip',general),('retry_clip_queue_job',single),('bulk_retry_clip_queue_jobs',bulk)]:source=replace(source,name,fn)
    compile(source,'main.py','exec');return source
