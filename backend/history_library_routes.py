"""History library endpoints. Plans are reviewed before reversible cleanup."""
import asyncio
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from history_library import HistoryLibrary

router = APIRouter(prefix='/api/history-library', tags=['history-library'])
_LOCK = asyncio.Lock()


def service():
    from db import DB_PATH
    from media_contract import STORAGE_DIR
    return HistoryLibrary(DB_PATH, STORAGE_DIR)


class CleanupRequest(BaseModel):
    mode: str = 'all'
    cutoff: str | None = None
    fingerprint: str | None = None


@router.post('/cleanup/preview')
async def preview(body: CleanupRequest):
    try:
        plan = await asyncio.to_thread(service().preview, body.mode, body.cutoff)
        # Row snapshots stay on the server, not in the browser.
        return {'mode': plan['mode'], 'cutoff': plan['cutoff'], 'fingerprint': plan['fingerprint'],
                'bytes': plan['bytes'], 'count': len(plan['groups']),
                'groups': [{'id': x['group']['id'], 'label': x['group'].get('label'),
                            'published': x['published'], 'files': len(x['files'])} for x in plan['groups']]}
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


@router.post('/cleanup/apply')
async def apply(body: CleanupRequest):
    if not body.fingerprint or not body.cutoff:
        raise HTTPException(422, '请先预览')
    # Never accept a client cutoff newer than the three-calendar-month rule.
    from history_library import date, three_months_before
    from datetime import datetime, timezone
    cutoff = date(body.cutoff)
    if cutoff is None or cutoff > three_months_before(datetime.now(timezone.utc)):
        raise HTTPException(422, '仅允许清理三个月以前的成片')
    async with _LOCK:
        try:
            return await asyncio.to_thread(service().execute, body.mode, body.cutoff, body.fingerprint)
        except (ValueError, OSError) as e:
            raise HTTPException(409, str(e)) from e


@router.get('/cleanup/batches')
async def batches():
    import json
    root = service().quarantine
    result = []
    for p in sorted(root.glob('*/journal.json'), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            j = json.loads(p.read_text(encoding='utf-8'))
            result.append({'batch_id': j['batch_id'], 'state': j['state'],
                           'count': len(j['plan']['groups']), 'bytes': j['plan']['bytes']})
        except (OSError, ValueError, KeyError):
            continue
    return result


@router.post('/cleanup/{batch}/restore')
async def restore(batch: str):
    async with _LOCK:
        try:
            return await asyncio.to_thread(service().restore, batch)
        except (ValueError, OSError) as e:
            raise HTTPException(409, str(e)) from e


@router.get('/catalogue-names')
async def catalogue_names():
    from wig_catalog_names import hairstyle_name
    with service().connect() as con:
        rows = service().rows(con, 'products')
    return [{'id': r['id'], 'name': hairstyle_name(r.get('product_name')),
             'product_name': r.get('product_name'), 'room_id': r.get('room_id'),
             'product_url': r.get('product_url')} for r in rows if r.get('enabled')]


class InspectRequest(BaseModel):
    recording_ids: list[int]


def resolution_service():
    from recording_resolution import RecordingResolution
    base = service()
    from media_contract import resolve_media_file
    return RecordingResolution(base.database, base.storage, resolver=resolve_media_file)


@router.post('/recordings/inspect')
async def inspect_recordings(body: InspectRequest):
    try:
        return await asyncio.to_thread(resolution_service().inspect, body.recording_ids)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


class DiscardRequest(InspectRequest):
    fingerprint: str


@router.post('/recordings/quarantine')
async def quarantine_recordings(body: DiscardRequest):
    async with _LOCK:
        try:
            return await asyncio.to_thread(resolution_service().execute_low, body.recording_ids, body.fingerprint)
        except (ValueError, OSError) as e:
            raise HTTPException(409, str(e)) from e


@router.get('/recordings/batches')
async def recording_batches():
    import json
    result = []
    for p in resolution_service().quarantine.glob('*/journal.json'):
        try:
            j = json.loads(p.read_text(encoding='utf-8'))
            result.append({'batch_id': j['batch_id'], 'state': j['state'], 'count': len(j['entries'])})
        except (ValueError, KeyError, OSError):
            continue
    return result


@router.post('/recordings/{batch}/restore')
async def restore_recordings(body: dict, batch: str):
    async with _LOCK:
        try:
            return await asyncio.to_thread(resolution_service().restore_low, batch)
        except (ValueError, OSError) as e:
            raise HTTPException(409, str(e)) from e


@router.get('/recordings/{recording_id}/hairstyle-evidence')
async def hairstyle_evidence(recording_id: int):
    """Read original subtitles; no inference, cutting or archive writes."""
    def run():
        import hashlib
        from media_contract import resolve_media_file, srt_candidates
        from wig_transcript_evidence import parse_srt, catalogue_mentions
        if recording_id <= 0:
            raise ValueError('无效录像ID')
        base = service()
        con = base.connect()
        try:
            row = con.execute('SELECT * FROM recordings WHERE id=?', (recording_id,)).fetchone()
            if row is None or row['local_deleted'] or not row['end_time']:
                raise ValueError('录像不存在、已弃用或尚未录制完成')
            row = dict(row)
            products = [p for p in base.rows(con, 'products')
                        if p.get('enabled') and p.get('room_id') in (None, row['room_id'])]
        finally:
            con.close()
        source = resolve_media_file(row['filename'])
        if not source:
            raise ValueError('源录像不在本机或不可访问')
        root = base.storage.resolve()
        if not source.resolve().is_relative_to(root):
            raise ValueError('源录像不在本机存储目录')
        subtitle = next((p for p in srt_candidates(source)
                         if p.resolve().is_relative_to(root) and p.is_file()), None)
        if not subtitle:
            raise ValueError('没有原始字幕，尚不能核对口播证据')
        with subtitle.open('rb') as f:
            raw = f.read(8*1024*1024+1)
        if len(raw) > 8*1024*1024:
            raise ValueError('字幕超过单次检查范围，请分批检查')
        cues = parse_srt(raw.decode('utf-8-sig'))
        hits = catalogue_mentions(cues, products)
        return {'recording_id': recording_id, 'filename': row['filename'], 'read_only': True,
                'time_basis': 'original_video_seconds', 'subtitle_sha256': hashlib.sha256(raw).hexdigest(),
                'cue_count': len(cues), 'mention_count': len(hits), 'truncated': len(hits)>500,
                'mentions': hits[:500], 'visual_verified': False,
                'note': '口播候选不代表画面正在展示该款；尚未生成分段或归档文件'}
    try:
        return await asyncio.to_thread(run)
    except (ValueError, OSError) as e:
        raise HTTPException(409, str(e)) from e
