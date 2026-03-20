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
            # publish columns
            "ALTER TABLE clip_groups ADD COLUMN publish_status INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE clip_groups ADD COLUMN post_title TEXT",
            "ALTER TABLE clip_groups ADD COLUMN post_caption TEXT",
            "ALTER TABLE clip_groups ADD COLUMN post_hashtags TEXT",
            "ALTER TABLE clip_groups ADD COLUMN published_url TEXT",
            "ALTER TABLE clip_groups ADD COLUMN published_at TEXT",
        ]:
            try:
                await db.execute(migration)
                await db.commit()
            except Exception:
                pass  # Column already exists
        await db.commit()


async def get_db():
    return aiosqlite.connect(DB_PATH)
