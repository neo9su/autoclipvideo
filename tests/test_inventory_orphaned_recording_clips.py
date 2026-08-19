import json
import sqlite3
from pathlib import Path

from scripts.inventory_orphaned_recording_clips import (
    build_report,
    inventory_database,
    parse_range,
)


def create_inventory_database(path: Path, include_recording: bool = True) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE recordings (
            id INTEGER PRIMARY KEY, room_id INTEGER, group_id INTEGER,
            filename TEXT, start_time TEXT, end_time TEXT, synced INTEGER,
            transcribed INTEGER, clipped INTEGER, local_deleted INTEGER,
            duration_status TEXT
        );
        CREATE TABLE clip_groups (
            id INTEGER PRIMARY KEY, room_id INTEGER, label TEXT,
            merge_status INTEGER, classic_status INTEGER, director_status INTEGER,
            creative_status INTEGER, realistic_status INTEGER, conservative_status INTEGER,
            qianchuan_status INTEGER, merged_filename TEXT, director_final_video TEXT,
            creative_final_video TEXT, realistic_final_video TEXT, conservative_final_video TEXT
        );
        CREATE TABLE recording_clips (
            id INTEGER PRIMARY KEY, recording_id INTEGER, variant_idx INTEGER,
            clip_filename TEXT, thumbnail TEXT, created_at TEXT, gpu_clip_job_id TEXT
        );
        INSERT INTO clip_groups VALUES (9, 1, 'batch', 2, 2, 1, 0, 2, 1, 0,
          'classic.mp4', 'director.mp4', NULL, 'realistic.mp4', NULL);
        INSERT INTO recording_clips VALUES
          (4675, 1887, 0, 'clip-a.mp4', NULL, '2026-08-20', NULL),
          (4694, 1888, 1, 'clip-b.mp4', NULL, '2026-08-20', NULL);
        """
    )
    if include_recording:
        connection.execute(
            "INSERT INTO recordings VALUES (1887, 1, 9, 'source.mp4', 'start', NULL, 1, 2, 2, 0, 'ok')"
        )
    connection.commit()
    connection.close()


def test_inventory_is_read_only_and_reports_recording_and_versions(tmp_path):
    database = tmp_path / "inventory.db"
    create_inventory_database(database)

    report = inventory_database(str(database), (4675, 4694), authoritative=True)

    assert report["found_clip_count"] == 2
    assert report["referenced_recording_ids"] == [1887, 1888]
    assert report["orphaned_clip_ids"] == [4694]
    first = report["clips"][0]
    assert first["recording"]["group_id"] == 9
    assert first["group"]["realistic_status"] == 2
    assert first["group"]["conservative_status"] == 1
    assert sqlite3.connect(database).execute("PRAGMA query_only").fetchone()[0] == 0


def test_compare_classifies_divergent_copies(tmp_path):
    production = tmp_path / "production.db"
    backup = tmp_path / "backup.db"
    create_inventory_database(production)
    create_inventory_database(backup, include_recording=True)
    connection = sqlite3.connect(backup)
    connection.execute("DELETE FROM recording_clips WHERE id = 4694")
    connection.commit()
    connection.close()

    report = build_report([str(production), str(backup)], (4675, 4694))

    assert report["read_only"] is True
    assert report["mutation_performed"] is False
    assert report["comparison"]["classification"] == "differs_across_supplied_databases"
    json.dumps(report)


def test_parse_range_validates_order():
    assert parse_range("4675-4694") == (4675, 4694)
    try:
        parse_range("4694-4675")
    except Exception as error:
        assert "positive IDs in order" in str(error)
    else:
        raise AssertionError("reversed range must fail")
