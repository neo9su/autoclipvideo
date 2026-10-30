"""Reversible, journalled cleanup of obsolete generated media and their groups."""
from calendar import monthrange
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid

ACTIVE = {'pending', 'scheduled', 'publishing'}
OUTPUT_FIELDS = {'merged_filename', 'capcut_export_filename', 'director_final_video',
                 'creative_final_video', 'qianchuan_final_video', 'qianchuan_preview_video',
                 'realistic_final_video', 'conservative_final_video', 'qianchuan_v2_final_video',
                 'codex_final_video'}


def three_months_before(now):
    index = now.year * 12 + now.month - 1 - 3
    year, month = divmod(index, 12)
    return now.replace(year=year, month=month+1, day=min(now.day, monthrange(year, month+1)[1]))


def date(value):
    try:
        d = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


class HistoryLibrary:
    def __init__(self, database, storage):
        self.database = Path(database)
        self.storage = Path(storage).resolve()
        self.quarantine = self.storage / '_recoverable_cleanup'

    def connect(self):
        con = sqlite3.connect(self.database, timeout=30)
        con.row_factory = sqlite3.Row
        return con

    def rows(self, con, table):
        if not con.execute('SELECT 1 FROM sqlite_master WHERE type="table" AND name=?', (table,)).fetchone():
            return []
        return [dict(r) for r in con.execute('SELECT * FROM ' + table)]

    def path(self, value):
        if not value:
            return None
        key = str(value)
        cache = getattr(self, '_path_cache', None)
        if cache is not None and key in cache:
            return cache[key]
        p = Path(key)
        if not p.is_absolute():
            p = self.storage / p
        # Reject other drives/network shares before filesystem resolution.
        # Path.resolve on an offline UNC share may block for minutes.
        p = Path(os.path.abspath(p))
        result = None
        try:
            if p.is_relative_to(self.storage) and not p.is_relative_to(self.quarantine) and not p.is_symlink():
                resolved = p.resolve()
                if resolved.is_relative_to(self.storage) and not resolved.is_relative_to(self.quarantine) and resolved.is_file():
                    result = resolved
        except OSError:
            self._path_errors.add(key)
        if cache is not None:
            cache[key] = result
        return result

    def preview(self, mode='all', cutoff=None):
        self._path_cache = {}
        self._path_errors = set()
        if mode not in {'all', 'published', 'unpublished'}:
            raise ValueError('无效的发布状态')
        cutoff = date(cutoff) if cutoff else three_months_before(datetime.now(timezone.utc))
        if cutoff is None:
            raise ValueError('无效截止时间')
        with self.connect() as con:
            tables = {t: self.rows(con, t) for t in ('clip_groups', 'recordings', 'recording_clips', 'publish_tasks')}
        groups = []
        for g in tables['clip_groups']:
            created = date(g.get('created_at'))
            if not created or created >= cutoff:
                continue
            tasks = [p for p in tables['publish_tasks'] if p.get('group_id') == g['id']]
            if any(p.get('status') in ACTIVE for p in tasks):
                continue
            if any(g.get(k) == 1 for k in g if k.endswith('_status')):
                continue
            published = any(p.get('status') == 'done' or p.get('manual_published') for p in tasks)
            if mode == 'published' and not published or mode == 'unpublished' and published:
                continue
            recs = [r for r in tables['recordings'] if r.get('group_id') == g['id']]
            if any(r.get('clipped') == 1 or r.get('transcribed') == 1 or not r.get('end_time') for r in recs):
                continue
            ids = {r['id'] for r in recs}
            clips = [r for r in tables['recording_clips'] if r.get('recording_id') in ids]
            outputs = [g.get(k) for k in OUTPUT_FIELDS] + [r.get('clip_filename') for r in recs+clips] + [p.get('video_path') for p in tasks]
            # Do not classify an unprocessed group as old completed media.
            if not any(outputs):
                continue
            files = {str(p): {'path': str(p), 'size': p.stat().st_size, 'mtime_ns': p.stat().st_mtime_ns}
                     for v in outputs if (p := self.path(v))}
            if any(str(v) in self._path_errors for v in outputs if v):
                continue
            if any(datetime.fromtimestamp(f['mtime_ns']/1e9, timezone.utc) >= cutoff for f in files.values()):
                continue
            groups.append({'group': g, 'recordings': recs, 'clips': clips, 'tasks': tasks,
                           'published': published, 'files': list(files.values())})
        selected = {x['group']['id'] for x in groups}
        selected_recs = {r['id'] for x in groups for r in x['recordings']}
        # Resolve references only when their basename could refer to an output
        # in this plan. Most historical sources live on offline archive shares.
        candidate_paths = {f['path'] for item in groups for f in item['files']}
        candidate_names = {Path(p).name.casefold() for p in candidate_paths}
        protected = set()
        for r in tables['recordings']:
            value = r.get('filename')
            if value and Path(str(value)).name.casefold() in candidate_names:
                # Conservatively protect same-basename source aliases even if
                # an archive share is currently unavailable.
                protected.update(p for p in candidate_paths if Path(p).name.casefold() == Path(str(value)).name.casefold())
        for table, rows in tables.items():
            for row in rows:
                own = (row.get('id') in selected if table == 'clip_groups' else
                       row.get('id') in selected_recs if table == 'recordings' else
                       row.get('recording_id') in selected_recs if table == 'recording_clips' else
                       row.get('group_id') in selected)
                if not own:
                    for key, value in row.items():
                        if key in OUTPUT_FIELDS or key in {'filename', 'clip_filename', 'video_path'}:
                            if value and Path(str(value)).name.casefold() in candidate_names:
                                protected.update(p for p in candidate_paths if Path(p).name.casefold() == Path(str(value)).name.casefold())
        for item in groups:
            item['files'] = [f for f in item['files'] if f['path'] not in protected]
        plan = {'mode': mode, 'cutoff': cutoff.isoformat(), 'groups': groups}
        plan['fingerprint'] = fingerprint(plan)
        plan['bytes'] = sum(f['size'] for item in groups for f in item['files'])
        return plan

    def execute(self, mode, cutoff, expected):
        plan = self.preview(mode, cutoff)
        if plan['fingerprint'] != expected:
            raise ValueError('候选记录已变化，请重新预览')
        batch = uuid.uuid4().hex
        root = self.quarantine / batch
        root.mkdir(parents=True)
        journal = {'batch_id': batch, 'state': 'prepared', 'plan': plan, 'moves': []}
        for item in plan['groups']:
            for f in item['files']:
                if not any(m['source'] == f['path'] for m in journal['moves']):
                    journal['moves'].append({'source': f['path'], 'target': str(root/'files'/str(len(journal['moves']))), **f})
        def save():
            temp = root/'journal.tmp'
            temp.write_text(json.dumps(journal, ensure_ascii=False, indent=2), encoding='utf-8')
            os.replace(temp, root/'journal.json')
        with self.connect() as con:
            with sqlite3.connect(root/'before.db') as backup:
                con.backup(backup)
            con.execute('BEGIN IMMEDIATE')
            if self.preview(mode, cutoff)['fingerprint'] != expected:
                raise ValueError('候选或引用发生变化，请重新预览')
            # Recheck row content under the write lock before touching media.
            for item in plan['groups']:
                current = con.execute('SELECT * FROM clip_groups WHERE id=?', (item['group']['id'],)).fetchone()
                if not current or dict(current) != item['group']:
                    raise ValueError('分组发生变化，请重新预览')
                for table, key in [('recordings','recordings'),('recording_clips','clips'),('publish_tasks','tasks')]:
                    for row in item[key]:
                        current = con.execute('SELECT * FROM '+table+' WHERE id=?', (row['id'],)).fetchone()
                        if not current or dict(current) != row:
                            raise ValueError('关联记录发生变化，请重新预览')
            save()
            try:
                for m in journal['moves']:
                    p = Path(m['source'])
                    if p.stat().st_size != m['size'] or p.stat().st_mtime_ns != m['mtime_ns']:
                        raise ValueError('文件已变化，请重新预览')
                    Path(m['target']).parent.mkdir(exist_ok=True)
                    os.replace(p, m['target'])
                for item in plan['groups']:
                    for task in item['tasks']:
                        con.execute('DELETE FROM publish_tasks WHERE id=?', (task['id'],))
                    for clip in item['clips']:
                        con.execute('DELETE FROM recording_clips WHERE id=?', (clip['id'],))
                    for rec in item['recordings']:
                        con.execute('UPDATE recordings SET group_id=NULL,clip_filename=NULL,clipped=-2 WHERE id=?', (rec['id'],))
                    con.execute('DELETE FROM clip_groups WHERE id=?', (item['group']['id'],))
                con.commit()
            except BaseException:
                con.rollback()
                for m in reversed(journal['moves']):
                    if Path(m['target']).exists(): os.replace(m['target'], m['source'])
                journal['state'] = 'reverted'
                save()
                raise
        journal['state'] = 'quarantined'
        save()
        return {'batch_id': batch, 'groups': len(plan['groups']), 'bytes': plan['bytes'], 'recoverable': True}

    def restore(self, batch):
        if not isinstance(batch, str) or len(batch) != 32 or any(c not in '0123456789abcdef' for c in batch):
            raise ValueError('无效批次')
        root = self.quarantine / batch
        journal = json.loads((root/'journal.json').read_text(encoding='utf-8'))
        if journal['state'] not in {'quarantined', 'prepared'}:
            raise ValueError('该批次已经恢复或不可恢复')
        with self.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            if journal['state'] == 'prepared':
                present = [con.execute('SELECT 1 FROM clip_groups WHERE id=?', (item['group']['id'],)).fetchone() is not None for item in journal['plan']['groups']]
                if present and all(present):
                    for m in journal['moves']:
                        if Path(m['target']).exists() and Path(m['source']).exists():
                            raise ValueError('恢复路径被占用')
                    for m in journal['moves']:
                        if Path(m['target']).exists(): os.replace(m['target'], m['source'])
                    journal['state'] = 'restored'
                    (root/'journal.json').write_text(json.dumps(journal, ensure_ascii=False, indent=2), encoding='utf-8')
                    return {'batch_id': batch, 'restored': True}
                if any(present):
                    raise ValueError('批次状态不一致，保留现场')
            for item in journal['plan']['groups']:
                if con.execute('SELECT 1 FROM clip_groups WHERE id=?', (item['group']['id'],)).fetchone():
                    raise ValueError('分组ID已被使用，停止恢复')
                for rec in item['recordings']:
                    row = con.execute('SELECT * FROM recordings WHERE id=?', (rec['id'],)).fetchone()
                    expected = dict(rec, group_id=None, clip_filename=None, clipped=-2)
                    if not row or dict(row) != expected:
                        raise ValueError('录像记录已变化，停止恢复')
                for table, key in [('publish_tasks', 'tasks'), ('recording_clips', 'clips')]:
                    for row in item[key]:
                        if con.execute('SELECT 1 FROM '+table+' WHERE id=?', (row['id'],)).fetchone():
                            raise ValueError('关联ID已被使用，停止恢复')
            for m in journal['moves']:
                if Path(m['source']).exists() or not Path(m['target']).is_file():
                    raise ValueError('恢复路径被占用或回收文件缺失')
            moved = []
            try:
                for m in journal['moves']:
                    os.replace(m['target'], m['source'])
                    moved.append(m)
                for item in journal['plan']['groups']:
                    for table, records in [('clip_groups', [item['group']]), ('publish_tasks', item['tasks']), ('recording_clips', item['clips'])]:
                        for row in records:
                            keys = list(row)
                            con.execute('INSERT INTO '+table+' ('+','.join(keys)+') VALUES ('+','.join('?' for _ in keys)+')', [row[k] for k in keys])
                    for rec in item['recordings']:
                        con.execute('UPDATE recordings SET group_id=?,clip_filename=?,clipped=? WHERE id=?', (rec.get('group_id'), rec.get('clip_filename'), rec.get('clipped'), rec['id']))
                con.commit()
            except BaseException:
                con.rollback()
                for m in reversed(moved): os.replace(m['source'], m['target'])
                raise
        journal['state'] = 'restored'
        (root/'journal.json').write_text(json.dumps(journal, ensure_ascii=False, indent=2), encoding='utf-8')
        return {'batch_id': batch, 'restored': True}
