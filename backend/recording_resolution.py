"""Bounded resolution checks and reversible quarantine of unused local sources."""
import json
import os
from pathlib import Path
import subprocess
import uuid
from history_library import HistoryLibrary, fingerprint
from wig_catalog_names import resolution_policy

FIELDS = ('local_deleted', 'clipped', 'transcribed', 'skip_reason')
MARK = {'local_deleted': 1, 'clipped': -2, 'transcribed': -2, 'skip_reason': '低于1080P，已移入可恢复区'}


def probe(path):
    proc = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height', '-of', 'json', str(path)],
        capture_output=True, text=True, timeout=15, check=True)
    stream = json.loads(proc.stdout)['streams'][0]
    return stream['width'], stream['height']


class RecordingResolution(HistoryLibrary):
    def __init__(self, database, storage, prober=probe):
        super().__init__(database, storage)
        self.quarantine = self.storage / '_recoverable_low_resolution'
        self.prober = prober
        self._path_errors = set()

    def inspect(self, ids, con=None):
        ids = list(dict.fromkeys(ids))
        if not ids or len(ids) > 100 or any(type(i) is not int or i <= 0 for i in ids):
            raise ValueError('每批选择1至100个有效录像ID')
        if con is None:
            with self.connect() as connection:
                return self.inspect(ids, connection)
        result = []
        for rid in ids:
            row = con.execute('SELECT * FROM recordings WHERE id=?', (rid,)).fetchone()
            item = {'id': rid, 'action': 'review', 'reason': 'missing_recording'}
            result.append(item)
            if row is None:
                continue
            row = dict(row)
            item['filename'] = row['filename']
            if row.get('group_id') is not None or row.get('clip_filename'):
                item['reason'] = 'linked_material'; continue
            if not row.get('end_time') or row.get('local_deleted') or any(row.get(k) in (0, 1) for k in ('transcribed', 'clipped')):
                item['reason'] = 'active_or_unavailable'; continue
            if con.execute('SELECT 1 FROM recording_clips WHERE recording_id=? LIMIT 1', (rid,)).fetchone():
                item['reason'] = 'linked_material'; continue
            # Duplicate source references cannot be discarded independently.
            if con.execute('SELECT 1 FROM recordings WHERE filename LIKE ? AND id!=? LIMIT 1', ('%' + str(row['filename']).replace('\\', '/').rsplit('/', 1)[-1], rid)).fetchone():
                item['reason'] = 'shared_source'; continue
            try:
                path = self.path(row['filename'])
                if not path:
                    item['reason'] = 'missing_or_external_file'; continue
                stat = path.stat()
                width, height = self.prober(path)
                after = path.stat()
                if (stat.st_size, stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    item['reason'] = 'source_changed'; continue
                item.update(resolution_policy(width, height), width=width, height=height)
                if item['action'] == 'quarantine':
                    item.update(source=str(path), size=stat.st_size, mtime_ns=stat.st_mtime_ns,
                                original={k: row[k] for k in FIELDS})
            except (OSError, ValueError, KeyError, IndexError, TypeError, subprocess.SubprocessError):
                item.update(action='review', reason='probe_failed')
        return {'recordings': result, 'fingerprint': fingerprint(result),
                'count': sum(x['action'] == 'quarantine' for x in result),
                'bytes': sum(x.get('size', 0) for x in result if x['action'] == 'quarantine')}

    @staticmethod
    def journal(path, value):
        temp = path.with_suffix('.tmp')
        with temp.open('w', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.flush(); os.fsync(f.fileno())
        temp.replace(path)

    def execute_low(self, ids, token):
        # Reprobe before taking the write lock, then check every row/file under
        # that lock. A worker claiming the row invalidates the whole preview.
        plan = self.inspect(ids)
        if plan['fingerprint'] != token or not plan['count']:
            raise ValueError('预览已变化或没有可弃用录像，请重新检查')
        batch = uuid.uuid4().hex
        directory = self.quarantine / batch
        directory.mkdir(parents=True)
        entries = [x for x in plan['recordings'] if x['action'] == 'quarantine']
        for x in entries:
            x['destination'] = str(directory / (str(x['id']) + Path(x['source']).suffix))
        journal = {'batch_id': batch, 'state': 'prepared', 'entries': entries}
        jp = directory / 'journal.json'
        self.journal(jp, journal)
        moved = []
        with self.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            try:
                for x in entries:
                    row = dict(con.execute('SELECT * FROM recordings WHERE id=?', (x['id'],)).fetchone())
                    if any(row[k] != x['original'][k] for k in FIELDS) or row.get('group_id') is not None or row.get('clip_filename') or not row.get('end_time'):
                        raise ValueError('录像状态已变化')
                    if con.execute('SELECT 1 FROM recording_clips WHERE recording_id=?', (x['id'],)).fetchone() or con.execute('SELECT 1 FROM recordings WHERE filename LIKE ? AND id!=?', ('%' + str(row['filename']).replace('\\', '/').rsplit('/', 1)[-1], x['id'])).fetchone():
                        raise ValueError('录像新增了引用')
                    p = Path(x['source']); st = p.stat()
                    if row['filename'] != x['filename'] or st.st_size != x['size'] or st.st_mtime_ns != x['mtime_ns'] or self.path(row['filename']) != p:
                        raise ValueError('源录像已变化')
                    p.rename(x['destination']); moved.append(x)
                    con.execute('UPDATE recordings SET local_deleted=?,clipped=?,transcribed=?,skip_reason=? WHERE id=?', (*MARK.values(), x['id']))
                con.commit()
            except BaseException:
                con.rollback()
                for x in reversed(moved):
                    Path(x['destination']).rename(x['source'])
                journal['state'] = 'rolled_back'; self.journal(jp, journal)
                raise
        journal['state'] = 'quarantined'; self.journal(jp, journal)
        return {'batch_id': batch, 'count': len(entries)}

    def restore_low(self, batch):
        if len(batch) != 32 or any(c not in '0123456789abcdef' for c in batch):
            raise ValueError('无效批次')
        jp = self.quarantine / batch / 'journal.json'
        journal = json.loads(jp.read_text(encoding='utf-8'))
        if journal['state'] not in ('prepared', 'quarantined'):
            raise ValueError('批次不可恢复')
        moved = []
        with self.connect() as con:
            con.execute('BEGIN IMMEDIATE')
            try:
                # Preflight the entire batch, including interrupted operations.
                for x in journal['entries']:
                    row = con.execute('SELECT * FROM recordings WHERE id=?', (x['id'],)).fetchone()
                    if row is None or row['filename'] != x['filename'] or row['group_id'] is not None or row['clip_filename']:
                        raise ValueError('录像记录冲突')
                    if con.execute('SELECT 1 FROM recording_clips WHERE recording_id=?', (x['id'],)).fetchone():
                        raise ValueError('录像新增了片段引用')
                    state = {k: row[k] for k in FIELDS}
                    if state not in (MARK, x['original']):
                        raise ValueError('录像状态已修改，停止恢复')
                    src, dst = Path(x['source']), Path(x['destination'])
                    if src.exists() == dst.exists():
                        raise ValueError('文件缺失或原路径已被占用')
                    st = (dst if dst.exists() else src).stat()
                    if st.st_size != x['size'] or st.st_mtime_ns != x['mtime_ns']:
                        raise ValueError('录像文件已修改')
                for x in journal['entries']:
                    dst = Path(x['destination'])
                    if dst.exists():
                        dst.rename(x['source']); moved.append(x)
                    con.execute('UPDATE recordings SET local_deleted=?,clipped=?,transcribed=?,skip_reason=? WHERE id=?',
                                (*(x['original'][k] for k in FIELDS), x['id']))
                con.commit()
            except BaseException:
                con.rollback()
                for x in reversed(moved):
                    Path(x['source']).rename(x['destination'])
                raise
        journal['state'] = 'restored'; self.journal(jp, journal)
        return {'batch_id': batch, 'state': 'restored'}
