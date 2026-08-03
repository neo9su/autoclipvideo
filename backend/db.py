import aiosqlite
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "douyin.db")

# Use a longer timeout to avoid "database is locked" under concurrent writes
_DB_TIMEOUT = 30


def aio_connect(path: str = None, timeout: float = None):
    """Return an aiosqlite connection with a sane default timeout."""
    return aiosqlite.connect(
        path or DB_PATH,
        timeout=timeout or _DB_TIMEOUT,
    )


async def _ensure_columns(db, table: str, columns: dict) -> None:
    """Idempotently add missing columns and verify schema after migration."""
    async with db.execute(f"PRAGMA table_info({table})") as cur:
        existing = {row[1] for row in await cur.fetchall()}
    for name, definition in columns.items():
        if name in existing:
            continue
        await db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
    await db.commit()
    async with db.execute(f"PRAGMA table_info({table})") as cur:
        after = {row[1] for row in await cur.fetchall()}
    missing = [name for name in columns if name not in after]
    if missing:
        raise RuntimeError(f"Missing columns on {table}: {', '.join(missing)}")


async def init_db():
    async with aio_connect() as db:
        # WAL mode: readers never block writers, writers never block readers
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")  # safe with WAL
        await db.execute("PRAGMA busy_timeout=30000")   # 30s busy retry
        await db.commit()
        await db.execute("""
            CREATE TABLE IF NOT EXISTS rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS recordings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                size_bytes INTEGER,
                synced INTEGER NOT NULL DEFAULT 0,
                segment_index INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (room_id) REFERENCES rooms(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS clip_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL,
                wig_model TEXT,
                wig_color TEXT,
                label TEXT NOT NULL DEFAULT '未分类',
                merge_status INTEGER NOT NULL DEFAULT 0,
                merged_filename TEXT,
                merged_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                editing_mode TEXT DEFAULT 'director',
                director_config TEXT,
                director_status INTEGER DEFAULT 0,
                director_script TEXT,
                director_segments TEXT,
                director_audio_path TEXT,
                director_final_video TEXT,
                director_error TEXT,
                qianchuan_status INTEGER DEFAULT 0,
                qianchuan_script TEXT,
                qianchuan_segments TEXT,
                qianchuan_audio_path TEXT,
                qianchuan_final_video TEXT,
                qianchuan_error TEXT,
                qianchuan_score REAL,
                qianchuan_review TEXT,
                vibe TEXT DEFAULT 'trendy'
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL DEFAULT 'douyin',
                product_id TEXT,
                product_name TEXT NOT NULL,
                product_url TEXT,
                keywords TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS publish_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                account_name TEXT NOT NULL,
                cookie_file TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS publish_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                platform TEXT NOT NULL,
                account_id INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                scheduled_at TEXT,
                title TEXT,
                description TEXT,
                tags TEXT,
                product_id INTEGER,
                video_path TEXT,
                published_at TEXT,
                error_msg TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (group_id) REFERENCES clip_groups(id),
                FOREIGN KEY (account_id) REFERENCES publish_accounts(id),
                FOREIGN KEY (product_id) REFERENCES products(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS recording_clips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recording_id INTEGER NOT NULL,
                variant_idx INTEGER NOT NULL DEFAULT 0,
                clip_filename TEXT NOT NULL,
                thumbnail TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (recording_id) REFERENCES recordings(id)
            )
        """)
        await db.commit()

        # Migrations
        for migration in [
            "ALTER TABLE recordings ADD COLUMN transcribed INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE recordings ADD COLUMN gpu_job_id TEXT",
            "ALTER TABLE recordings ADD COLUMN clipped INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE recordings ADD COLUMN clip_filename TEXT",
            "ALTER TABLE recordings ADD COLUMN analyzed INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE recordings ADD COLUMN wig_model TEXT",
            "ALTER TABLE recordings ADD COLUMN wig_color TEXT",
            "ALTER TABLE recordings ADD COLUMN session_label TEXT",
            "ALTER TABLE recordings ADD COLUMN has_tryon INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE recordings ADD COLUMN has_promotion INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE recordings ADD COLUMN group_id INTEGER",
            "ALTER TABLE recordings ADD COLUMN local_deleted INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE recordings ADD COLUMN thumbnail TEXT",
            "ALTER TABLE recordings ADD COLUMN clip_count INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE publish_tasks ADD COLUMN product_ids TEXT",
            "ALTER TABLE recordings ADD COLUMN transcribe_error TEXT",
            "ALTER TABLE clip_groups ADD COLUMN is_custom INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE publish_tasks ADD COLUMN no_cart INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE recordings ADD COLUMN reclip_feedback TEXT",
            "ALTER TABLE clip_groups ADD COLUMN quality_issue TEXT",
            "ALTER TABLE products ADD COLUMN room_id INTEGER",
            "ALTER TABLE recordings ADD COLUMN skip_reason TEXT",
            "ALTER TABLE clip_groups ADD COLUMN merge_error TEXT",
            # 双模式支持字段
            "ALTER TABLE clip_groups ADD COLUMN editing_mode TEXT DEFAULT 'director'",
            "ALTER TABLE clip_groups ADD COLUMN director_config TEXT",
            "ALTER TABLE clip_groups ADD COLUMN director_status INTEGER DEFAULT 0",
            "ALTER TABLE clip_groups ADD COLUMN director_script TEXT",
            "ALTER TABLE clip_groups ADD COLUMN director_segments TEXT",
            "ALTER TABLE clip_groups ADD COLUMN director_audio_path TEXT",
            "ALTER TABLE clip_groups ADD COLUMN director_final_video TEXT",
            "ALTER TABLE clip_groups ADD COLUMN director_error TEXT",
            "ALTER TABLE recordings ADD COLUMN preferred_editing_mode TEXT DEFAULT 'classic'",
            # Remote execution and transfer accounting; all are idempotent migrations.
            "ALTER TABLE recordings ADD COLUMN execution_node TEXT DEFAULT 'remote-gpu'",
            "ALTER TABLE recordings ADD COLUMN upload_bytes INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE recordings ADD COLUMN download_bytes INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE recordings ADD COLUMN transfer_attempts INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE recordings ADD COLUMN temp_file_count INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE recordings ADD COLUMN gpu_waiting INTEGER NOT NULL DEFAULT 0",
            # GPU offload tracking
            "ALTER TABLE recording_clips ADD COLUMN gpu_clip_job_id TEXT",
            # VibeVoice
            "ALTER TABLE clip_groups ADD COLUMN vibe TEXT DEFAULT 'trendy'",
            # Voice cloning: one voice reference per live room
            "ALTER TABLE rooms ADD COLUMN voice_ref_clip_job_id TEXT",
            # Dual-mode: independent status per pipeline + publish version selection
            "ALTER TABLE clip_groups ADD COLUMN classic_status INTEGER DEFAULT 0",
            "ALTER TABLE clip_groups ADD COLUMN publish_versions TEXT DEFAULT 'both'",
            # 三模式：自编模式（creative）流水线字段
            "ALTER TABLE clip_groups ADD COLUMN creative_status INTEGER DEFAULT 0",
            "ALTER TABLE clip_groups ADD COLUMN creative_error TEXT",
            "ALTER TABLE clip_groups ADD COLUMN creative_script TEXT",
            "ALTER TABLE clip_groups ADD COLUMN creative_audio_path TEXT",
            "ALTER TABLE clip_groups ADD COLUMN creative_final_video TEXT",
            # 商品缩略图
            "ALTER TABLE products ADD COLUMN product_thumb TEXT",
            # 发布重试计数
            "ALTER TABLE publish_tasks ADD COLUMN retry_count INTEGER DEFAULT 0",
            # 封面候选图 (JSON array of relative paths) 和已选封面
            "ALTER TABLE clip_groups ADD COLUMN cover_candidates TEXT",
            "ALTER TABLE clip_groups ADD COLUMN selected_cover TEXT",
            # 手动标记已发布（用户自行下载发布，不走系统发布）
            "ALTER TABLE publish_tasks ADD COLUMN manual_published INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE publish_tasks ADD COLUMN manual_published_at TEXT",
            # 千川投流版独立流水线字段（0 未开始 / 1 生成中 / 2 完成 / -2 商品不匹配 / -3 质量失败 / -4 编码或探测失败）
            "ALTER TABLE clip_groups ADD COLUMN qianchuan_status INTEGER DEFAULT 0",
            "ALTER TABLE clip_groups ADD COLUMN qianchuan_script TEXT",
            "ALTER TABLE clip_groups ADD COLUMN qianchuan_segments TEXT",
            "ALTER TABLE clip_groups ADD COLUMN qianchuan_audio_path TEXT",
            "ALTER TABLE clip_groups ADD COLUMN qianchuan_final_video TEXT",
            "ALTER TABLE clip_groups ADD COLUMN qianchuan_error TEXT",
            "ALTER TABLE clip_groups ADD COLUMN qianchuan_score REAL",
            "ALTER TABLE clip_groups ADD COLUMN qianchuan_review TEXT",
        ]:
            try:
                await db.execute(migration)
                await db.commit()
            except Exception:
                pass  # Column already exists

        await _ensure_columns(db, "clip_groups", {
            "qianchuan_status": "INTEGER DEFAULT 0",
            "qianchuan_script": "TEXT",
            "qianchuan_segments": "TEXT",
            "qianchuan_audio_path": "TEXT",
            "qianchuan_final_video": "TEXT",
            "qianchuan_error": "TEXT",
            "qianchuan_score": "REAL",
            "qianchuan_review": "TEXT",
        })

        # Backfill classic_status for existing merged groups (idempotent)
        await db.execute(
            "UPDATE clip_groups SET classic_status = 2 "
            "WHERE classic_status = 0 AND merged_filename IS NOT NULL AND merge_status = 2"
        )
        # Backfill director_status for existing director videos
        await db.execute(
            "UPDATE clip_groups SET director_status = 2 "
            "WHERE director_status = 0 AND director_final_video IS NOT NULL"
        )
        # Backfill qianchuan_status for existing qianchuan videos
        await db.execute(
            "UPDATE clip_groups SET qianchuan_status = 2 "
            "WHERE qianchuan_status = 0 AND qianchuan_final_video IS NOT NULL"
        )
        await db.commit()

        # Indexes (idempotent — CREATE INDEX IF NOT EXISTS)
        for idx_sql in [
            # Poll loop: find unsynced + in-flight transcriptions
            "CREATE INDEX IF NOT EXISTS idx_recordings_transcribed ON recordings(transcribed)",
            "CREATE INDEX IF NOT EXISTS idx_recordings_synced ON recordings(synced)",
            # Clip dispatch and crash-recovery
            "CREATE INDEX IF NOT EXISTS idx_recordings_clipped ON recordings(clipped)",
            # Group membership (used in every GROUP JOIN and merge_group)
            "CREATE INDEX IF NOT EXISTS idx_recordings_group_id ON recordings(group_id)",
            # Publish scheduler: filter by status + scheduled_at
            "CREATE INDEX IF NOT EXISTS idx_publish_tasks_status ON publish_tasks(status)",
            "CREATE INDEX IF NOT EXISTS idx_publish_tasks_group_id ON publish_tasks(group_id)",
            # recording_clips lookup by recording_id
            "CREATE INDEX IF NOT EXISTS idx_recording_clips_recording_id ON recording_clips(recording_id)",
        ]:
            try:
                await db.execute(idx_sql)
                await db.commit()
            except Exception:
                pass

        await db.commit()


async def get_db():
    return aiosqlite.connect(DB_PATH)
