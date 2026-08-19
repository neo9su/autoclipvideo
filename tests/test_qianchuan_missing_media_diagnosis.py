from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.diagnose_qianchuan_missing_media import diagnose_groups


def test_diagnosis_is_read_only_and_reports_missing_source_media(tmp_path: Path) -> None:
    database_path = tmp_path / "recorder.db"
    storage_root = tmp_path / "recordings"
    storage_root.mkdir()
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        CREATE TABLE clip_groups (
            id INTEGER PRIMARY KEY, label TEXT, qianchuan_status INTEGER,
            qianchuan_file_status TEXT, qianchuan_final_video TEXT
        );
        CREATE TABLE recordings (
            id INTEGER PRIMARY KEY, group_id INTEGER, filename TEXT,
            clip_filename TEXT, synced INTEGER, transcribed INTEGER,
            clipped INTEGER, local_deleted INTEGER, duration_status TEXT
        );
        INSERT INTO clip_groups VALUES (4675, 'group', -2, 'not_generated', NULL);
        INSERT INTO clip_groups VALUES (4685, 'successful', 2, 'ready', 'done.mp4');
        INSERT INTO recordings VALUES (20204, 4675, 'source.mp4', NULL, 1, 2, 2, 0, 'accepted');
        """
    )
    connection.commit()
    connection.close()

    report = diagnose_groups(str(database_path), str(storage_root), (4675, 4685))

    assert report["read_only"] is True
    affected = report["groups"][0]
    assert affected["qianchuan_status"] == -2
    assert affected["qianchuan_file_status"] == "not_generated"
    assert affected["recordings"][0]["evidence"]["ready"] is False
    assert "sync_mp4_to_storage" in report["operator_action"]

    connection = sqlite3.connect(database_path)
    assert connection.execute("SELECT qianchuan_status FROM clip_groups WHERE id = 4685").fetchone()[0] == 2
    connection.close()


def test_diagnosis_accepts_mp4_srt_sidecars(tmp_path: Path) -> None:
    database_path = tmp_path / "recorder.db"
    storage_root = tmp_path / "recordings"
    storage_root.mkdir()
    (storage_root / "source.mp4").write_bytes(b"mp4")
    (storage_root / "source.mp4.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n字幕\n", encoding="utf-8")
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        CREATE TABLE clip_groups (id INTEGER PRIMARY KEY, label TEXT, qianchuan_status INTEGER, qianchuan_final_video TEXT);
        CREATE TABLE recordings (id INTEGER, group_id INTEGER, filename TEXT, clip_filename TEXT, synced INTEGER, transcribed INTEGER, clipped INTEGER, local_deleted INTEGER, duration_status TEXT);
        INSERT INTO clip_groups VALUES (4675, 'group', -2, NULL);
        INSERT INTO recordings VALUES (20204, 4675, 'source.mp4', NULL, 1, 2, 2, 0, 'accepted');
        """
    )
    connection.commit()
    connection.close()

    evidence = diagnose_groups(str(database_path), str(storage_root), (4675,))["groups"][0]["recordings"][0]["evidence"]
    assert evidence["ready"] is True
    assert evidence["mp4"]["size_bytes"] == 3
    assert evidence["srt"]["readable"] is True
