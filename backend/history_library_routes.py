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


def recording_context(recording_id):
    from media_contract import resolve_media_file, resolve_srt_file
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
    subtitle = resolve_srt_file(row['filename'])
    if not subtitle or not subtitle.resolve().is_relative_to(root):
        raise ValueError('没有本机原始字幕，尚不能核对口播证据')
    with subtitle.open('rb') as f:
        raw = f.read(8*1024*1024+1)
    if len(raw) > 8*1024*1024:
        raise ValueError('字幕超过单次检查范围，请分批检查')
    return row, products, source, raw


@router.get('/recordings/{recording_id}/hairstyle-evidence')
async def hairstyle_evidence(recording_id: int):
    """Read original subtitles; no inference, cutting or archive writes."""
    def run():
        import hashlib
        from wig_transcript_evidence import parse_srt, catalogue_mentions
        row, products, source, raw = recording_context(recording_id)
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


class ArchiveBoundary(BaseModel):
    model_config = {'extra': 'forbid', 'allow_inf_nan': False}
    start_sec: float
    end_sec: float
    wig: str = ''
    color: str = ''
    features: list[str] = []
    current_evidence: str = ''


class ArchivePlanRequest(BaseModel):
    boundaries: list[ArchiveBoundary]


def library_index():
    from wig_library_index import WigLibraryIndex
    return WigLibraryIndex(service().storage / '_wig_library' / 'index.sqlite')


@router.post('/recordings/{recording_id}/archive-plan')
async def save_archive_plan(recording_id: int, body: ArchivePlanRequest):
    def run():
        import hashlib
        from wig_archive_plan import build_archive_plan
        from wig_catalog_names import resolution_policy
        boundaries = [b.model_dump() for b in body.boundaries]
        if not 1 <= len(boundaries) <= 100:
            raise ValueError('每次保存1至100个展示区间')
        for b in boundaries:
            if b['start_sec'] < 0 or b['end_sec'] <= b['start_sec'] or any(len(b[k])>500 for k in ('wig','color','current_evidence')) or len(b['features'])>12 or any(len(f)>80 for f in b['features']):
                raise ValueError('区间时间或名称特征无效')
            # Browser-entered labels are observations, never trusted vision results.
            b.update(visual_verified=False, identity_confirmed=False)
        row, products, source, raw = recording_context(recording_id)
        index = library_index()
        asset = index.register(source, recording_id, row['room_id'])
        if not resolution_policy(asset['metadata'].get('width'),asset['metadata'].get('height'))['usable']:
            raise ValueError('录像低于1080P，不创建剪辑计划')
        plan = build_archive_plan(recording_id,str(source),boundaries,products,srt_text=raw.decode('utf-8-sig'))
        return index.save_plan(asset,recording_id,plan,hashlib.sha256(raw).hexdigest())
    async with _LOCK:
        try:
            return await asyncio.to_thread(run)
        except (ValueError, OSError, KeyError, IndexError) as e:
            raise HTTPException(409,str(e)) from e


@router.get('/archive-plans')
async def list_archive_plans(recording_id: int | None = None):
    return await asyncio.to_thread(library_index().list_plans,recording_id)


@router.post('/archive-plans/{plan_id}/{action}')
async def change_archive_plan(plan_id: str, action: str):
    if action not in ('withdraw','restore'):
        raise HTTPException(422,'无效操作')
    async with _LOCK:
        try:
            return await asyncio.to_thread(library_index().set_state,plan_id,'withdrawn' if action=='withdraw' else 'active')
        except (ValueError,OSError) as e:
            raise HTTPException(409,str(e)) from e


def archive_renderer():
    from wig_archive_render import ArchiveRenderer
    return ArchiveRenderer(library_index(),service().storage)


@router.get('/archive-plans/{plan_id}/export-preview')
async def preview_archive_export(plan_id: str):
    def run():
        plan,asset,source=archive_renderer().prepare(plan_id)
        return {'plan_id':plan_id,'asset_id':asset['asset_id'],'count':len(plan['segments']),
                'duration_seconds':sum(s['end_sec']-s['start_sec'] for s in plan['segments']),
                'execution':'cpu','source_unchanged':True,'read_only':True}
    try:
        return await asyncio.to_thread(run)
    except (ValueError,OSError) as e:
        raise HTTPException(409,str(e)) from e


@router.post('/archive-exports/{plan_id}/create')
async def create_archive_export(plan_id: str):
    import subprocess
    async with _LOCK:
        try:
            job=await asyncio.to_thread(archive_renderer().export,plan_id)
            return {'batch_id':job['batch_id'],'state':job['state'],'files':len(job['files'])}
        except (ValueError,OSError,subprocess.SubprocessError) as e:
            raise HTTPException(409,str(e)) from e


@router.get('/archive-exports')
async def list_archive_exports():
    return await asyncio.to_thread(archive_renderer().list_batches)


@router.post('/archive-exports/{batch_id}/{action}')
async def change_archive_export(batch_id: str, action: str):
    import subprocess
    async with _LOCK:
        try:
            job=await asyncio.to_thread(archive_renderer().batch_state,batch_id,action)
            return {'batch_id':job['batch_id'],'state':job['state'],'files':len(job['files'])}
        except (ValueError,OSError,subprocess.SubprocessError) as e:
            raise HTTPException(409,str(e)) from e


class HomophoneReviewRequest(BaseModel):
    start_sec: float = 0
    end_sec: float = 600


@router.post('/recordings/{recording_id}/homophone-review')
async def homophone_review(recording_id: int, body: HomophoneReviewRequest):
    """Read-only candidate retrieval; never rewrite subtitles or attach a product."""
    def run():
        from wig_text_review import review_subtitles
        row, products, source, raw = recording_context(recording_id)
        result = review_subtitles(raw, products, body.start_sec, body.end_sec)
        return dict(result, recording_id=recording_id)
    try:
        # Bound optional worker concurrency without interfering with GPU services.
        async with _TEXT_REVIEW_LOCK:
            return await asyncio.to_thread(run)
    except (ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


_TEXT_REVIEW_LOCK = asyncio.Lock()


class ProductLinkEditRequest(BaseModel):
    product_url: str
    expected_before: str


@router.post('/products/{product_id}/link')
async def edit_product_link(product_id: int, body: ProductLinkEditRequest):
    from product_link_edit import edit_link
    base=service()
    async with _LOCK:
        try:
            return await asyncio.to_thread(edit_link,base.database,base.storage/'_product_link_edits',product_id,body.product_url,body.expected_before)
        except (ValueError,OSError) as exc:
            raise HTTPException(409,str(exc)) from exc


@router.post('/product-link-edits/{batch}/restore')
async def restore_product_link(batch: str):
    from product_link_edit import restore_link
    base=service()
    async with _LOCK:
        try:
            return await asyncio.to_thread(restore_link,base.database,base.storage/'_product_link_edits',batch)
        except (ValueError,OSError) as exc:
            raise HTTPException(409,str(exc)) from exc


@router.get('/products/{product_id}/link')
async def read_product_link(product_id: int):
    base=service()
    con=base.connect()
    try:
        row=con.execute('SELECT id,product_name,product_url FROM products WHERE id=?',(product_id,)).fetchone()
        if row is None:raise HTTPException(404,'商品不存在')
        return dict(row)
    finally:
        con.close()
