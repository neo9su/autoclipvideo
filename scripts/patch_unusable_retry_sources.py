"""Do not periodically retry groups whose associated recordings are unusable."""
OLD='AND EXISTS (SELECT 1 FROM recordings WHERE recordings.group_id = clip_groups.id)'
NEW="AND EXISTS (SELECT 1 FROM recordings WHERE recordings.group_id = clip_groups.id AND recordings.local_deleted = 0 AND recordings.transcribed = 2 AND recordings.end_time IS NOT NULL)"
def patch(source):
    start=source.index('async def _periodic_retry(')
    end=source.index('asyncio.create_task(_periodic_retry())',start)
    body=source[start:end]
    if body.count(OLD)!=2:raise RuntimeError('Periodic retry query drift')
    result=source[:start]+body.replace(OLD,NEW)+source[end:]
    compile(result,'transcribe.py','exec')
    return result
