import asyncio
import sys
import time
import types
from unittest.mock import patch as mock_patch
from backend.group_artifact_snapshot import GroupArtifactSnapshot
from scripts.patch_groups_event_loop import patch

SOURCE='''import asyncio,time
class App:
 def get(self,path):return lambda fn:fn
app=App()
_groups_cache=None
_API_CACHE_TTL_SECONDS=5
rows=[{'id':1,'label':'保留名称','merged_filename':'clip.mp4'}]
def _hair_traits(item):return {'hair_display':'保留发型'}
@app.get("/api/groups")
async def list_groups():
    global _groups_cache
    now=time.monotonic()
    if _groups_cache and now-_groups_cache[0] < _API_CACHE_TTL_SECONDS:
        return _groups_cache[1]
    result = [dict(r) | _artifact_statuses(dict(r)) | _hair_traits(dict(r)) for r in rows]
    _groups_cache = (now, result)
    return result
'''


def test_slow_file_io_does_not_block_other_requests_and_duplicate_reads_coalesce():
    namespace={};exec(patch(SOURCE),namespace)
    calls=[]
    def slow_probe(self,value):
        calls.append(value);time.sleep(.15);return '/actual/clip.mp4','ready'
    resolver=types.SimpleNamespace(_candidate_paths=lambda value:[])
    helper=types.SimpleNamespace(GroupArtifactSnapshot=GroupArtifactSnapshot)
    async def scenario():
        first=asyncio.create_task(namespace['list_groups']())
        second=asyncio.create_task(namespace['list_groups']())
        started=time.monotonic()
        await asyncio.sleep(.02)
        assert time.monotonic()-started < .10
        assert not first.done()
        result,duplicate=await asyncio.gather(first,second)
        assert result==duplicate
        assert result[0]['label']=='保留名称'
        assert result[0]['hair_display']=='保留发型'
        assert result[0]['classic_available'] is True
        assert result[0]['director_available'] is False
        assert len(calls)==1
        assert time.monotonic()-namespace['_groups_cache'][0] < .10
    with mock_patch.dict(sys.modules,{'group_artifact_snapshot':helper,'video_path_resolver':resolver}),mock_patch.object(GroupArtifactSnapshot,'_probe',slow_probe):
        asyncio.run(scenario())


def test_patch_rejects_reapplication():
    import pytest
    with pytest.raises(ValueError,match='Already patched'):patch(patch(SOURCE))
