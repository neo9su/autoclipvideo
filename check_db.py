import sqlite3
import os

db_path = 'C:/Users/neo/douyin_backend/backend/douyin.db'
conn = sqlite3.connect(db_path)
cursor = conn.execute('''
    SELECT id, filename, room_id, synced, transcribed, end_time, start_time
    FROM recordings
    WHERE id >= 7145
    ORDER BY id DESC
    LIMIT 10
''')
print("=== 最近录像记录 ===")
for r in cursor:
    print(f'ID={r[0]} room={r[2]} file={r[1]} synced={r[3]} transcribed={r[4]} start={r[6]} end={r[5]}')

# 检查文件是否存在
print("\n=== 文件存在性检查 ===")
recordings_dir = os.environ.get('RECORDINGS_DIR', 'C:\\Users\\neo\\douyin_recordings')
print(f"Recordings dir: {recordings_dir}")
cursor = conn.execute('''
    SELECT id, filename, room_id
    FROM recordings
    WHERE id >= 7145
    ORDER BY id DESC
    LIMIT 5
''')
for r in cursor:
    expected_path = os.path.join(recordings_dir, r[1])
    alt_path = os.path.join(recordings_dir, str(r[2]), r[1])
    print(f'ID={r[0]} file={r[1]}')
    print(f'  Expected: {expected_path} -> {os.path.exists(expected_path)}')
    print(f'  Alt path: {alt_path} -> {os.path.exists(alt_path)}')

conn.close()
