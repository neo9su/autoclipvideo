"""Dismiss failed jobs whose source has already been retired; preserve all assets.

Run on 203 with --database PATH --backup NEW_FILE, or --restore BACKUP_FILE.
Uses the application's existing dismissal marker. Never changes job status.
"""
import argparse
import json
import sqlite3
from pathlib import Path

MARKER = '已手动清除'
GUARD = ('local_deleted', 'clipped', 'transcribed', 'clip_error', 'transcribe_error')


def run(database, backup, restore=False):
    connection = sqlite3.connect(database, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('BEGIN IMMEDIATE')
        if restore:
            saved = json.loads(Path(backup).read_text(encoding='utf-8'))
            changed = 0
            for old in saved:
                current = connection.execute('SELECT * FROM recordings WHERE id=?', (old['id'],)).fetchone()
                if current and current['skip_reason'] == MARKER and all(current[k] == old[k] for k in GUARD):
                    connection.execute('UPDATE recordings SET skip_reason=? WHERE id=?', (old['skip_reason'], old['id']))
                    changed += 1
            result = {'restored': changed, 'skipped': len(saved) - changed}
        else:
            rows = [dict(r) for r in connection.execute(
                "SELECT * FROM recordings WHERE local_deleted=1 AND (clipped=-1 OR transcribed=-1) "
                "AND clipped!=1 AND transcribed!=1 AND coalesce(skip_reason,'')!=?", (MARKER,))]
            # Exclusive creation: an existing recovery archive is never overwritten.
            with Path(backup).open('x', encoding='utf-8') as handle:
                json.dump(rows, handle, ensure_ascii=False)
                handle.flush()
                import os
                os.fsync(handle.fileno())
            connection.executemany('UPDATE recordings SET skip_reason=? WHERE id=?', [(MARKER, r['id']) for r in rows])
            result = {'dismissed_records': len(rows), 'clip_failures': sum(r['clipped'] == -1 for r in rows),
                      'transcribe_failures': sum(r['transcribed'] == -1 for r in rows)}
        connection.commit()
        return result
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--backup')
    group.add_argument('--restore')
    args = parser.parse_args()
    print(json.dumps(run(args.database, args.restore or args.backup, bool(args.restore)), ensure_ascii=False))
