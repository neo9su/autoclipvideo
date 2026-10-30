"""Store a user-supplied finished video as a publishable custom group, without media jobs."""
import asyncio
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import sqlite3
import subprocess
import uuid

MAX_BYTES = 1_000_000_000


def probe_video(path):
    from publish_policy import validate_publish_duration
    try:
        process = subprocess.run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)],
            capture_output=True, timeout=30, check=True,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0)
        data = json.loads(process.stdout)
        video = next(item for item in data['streams'] if item.get('codec_type') == 'video')
        if not {'mov', 'mp4'}.intersection(data['format'].get('format_name', '').split(',')):
            raise ValueError('请上传MP4或MOV格式的视频')
        duration = float(data['format']['duration'])
        reason = validate_publish_duration(duration)
        if reason:
            raise ValueError(reason)
        if not video.get('width') or not video.get('height'):
            raise ValueError('无法读取视频画面尺寸')
        return dict(duration=duration, width=video['width'], height=video['height'], codec=video.get('codec_name'))
    except (subprocess.SubprocessError, KeyError, StopIteration, json.JSONDecodeError) as error:
        raise ValueError('无法读取视频，请上传有效的MP4或MOV成片') from error


def commit_video(db_path, folder, temp, sha, label, extension):
    """A transaction serializes same-content retries; never create recordings or publish tasks."""
    targets = [str(folder / ('manual_' + sha + ext)) for ext in ('.mp4', '.mov')]
    with closing(sqlite3.connect(db_path, timeout=30)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN IMMEDIATE')
        existing = db.execute('SELECT * FROM clip_groups WHERE is_custom=1 AND merged_filename IN (?,?) ORDER BY id LIMIT 1', targets).fetchone()
        room = db.execute("SELECT id FROM rooms WHERE url='__custom__'").fetchone()
        if existing:
            target = Path(existing['merged_filename'])
            group_id = existing['id']
        else:
            room_id = room['id'] if room else db.execute("INSERT INTO rooms(name,url,enabled) VALUES ('自定义上传','__custom__',0)").lastrowid
            target = folder / ('manual_' + sha + extension)
            columns = {row[1] for row in db.execute('PRAGMA table_info(clip_groups)')}
            fields = ['room_id','label','is_custom','editing_mode','publish_versions','merge_status','classic_status','merged_filename']
            values = [room_id,label,1,'manual_upload','classic',2,2,str(target)]
            if 'enabled' in columns:
                fields.append('enabled');values.append(0)
            group_id = db.execute('INSERT INTO clip_groups('+','.join(fields)+') VALUES ('+','.join('?' for _ in fields)+')', values).lastrowid
        # Only the freshly uploaded, checksum-named file is moved. Existing original footage is untouched.
        os.replace(temp, target)
        group = dict(db.execute('SELECT g.*,r.name AS room_name FROM clip_groups g LEFT JOIN rooms r ON r.id=g.room_id WHERE g.id=?',(group_id,)).fetchone())
    group.update(classic_available=True, classic_file_status='ready')
    return dict(group=group, sha256=sha, reused=bool(existing), reprocess=False, auto_publish=False)


def create_router(db_path, folder, probe=probe_video, max_bytes=MAX_BYTES):
    from fastapi import APIRouter, File, Form, HTTPException, UploadFile
    router = APIRouter()
    folder = Path(folder)

    @router.get('/api/publish-videos/capabilities')
    async def capabilities():
        from publish_policy import MIN_PUBLISH_DURATION_SECONDS, MAX_PUBLISH_DURATION_SECONDS
        return dict(formats=['mp4', 'mov'], max_bytes=max_bytes, min_duration=MIN_PUBLISH_DURATION_SECONDS, max_duration=MAX_PUBLISH_DURATION_SECONDS, reprocess=False, auto_publish=False)

    @router.post('/api/publish-videos/upload', status_code=201)
    async def upload(file: UploadFile = File(...), label: str = Form('')):
        filename = PureWindowsPath(file.filename or '').name
        extension = Path(filename).suffix.lower()
        if extension not in ('.mp4', '.mov'):
            raise HTTPException(422, '请选择MP4或MOV视频')
        title = label.strip() or Path(filename).stem
        if not title or len(title) > 200:
            raise HTTPException(422, '视频名称须为1–200字')
        if file.size is not None and file.size > max_bytes:
            raise HTTPException(413, '视频大小不能超过1000MB')
        temp = folder / ('.' + uuid.uuid4().hex + '.upload' + extension)
        handle = None
        try:
            await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
            handle = await asyncio.to_thread(temp.open, 'xb')
            size, digest = 0, hashlib.sha256()
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(413, '视频大小不能超过1000MB')
                def write_chunk():
                    handle.write(chunk)
                    digest.update(chunk)
                await asyncio.to_thread(write_chunk)
            await asyncio.to_thread(handle.close);handle = None
            if not size:
                raise HTTPException(422, '视频文件为空')
            try:
                metadata = await asyncio.to_thread(probe, temp)
            except ValueError as error:
                raise HTTPException(422, str(error)) from error
            result = await asyncio.to_thread(commit_video, db_path, folder, temp, digest.hexdigest(), title, extension)
            result.update(size_bytes=size, video=metadata)
            return result
        except OSError as error:
            raise HTTPException(507, '视频保存失败，请检查存储空间和网络盘连接') from error
        finally:
            if handle is not None:
                await asyncio.to_thread(handle.close)
            await asyncio.to_thread(temp.unlink, missing_ok=True)
            await file.close()
    return router
