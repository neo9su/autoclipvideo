import aiosqlite
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "douyin.db")


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
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
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
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
        ]:
            try:
                await db.execute(migration)
                await db.commit()
            except Exception:
                pass  # Column already exists
        await db.commit()


async def get_db():
    return aiosqlite.connect(DB_PATH)
