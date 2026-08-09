from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

from reclip_batch import Manifest, classify_error, discover_candidates, sha256_file, verify_immutable


def test_manifest_discovers_pairs_and_rejects_changed_input(tmp_path):
    source = tmp_path / "recordings"
    source.mkdir()
    mp4 = source / "sample.mp4"
    srt = source / "sample.srt"
    mp4.write_bytes(b"immutable video")
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")

    candidates = discover_candidates(source)
    assert len(candidates) == 1
    assert candidates[0].mp4_sha256 == sha256_file(mp4)

    manifest = Manifest(tmp_path / "checkpoint.db")
    try:
        assert manifest.import_candidates(candidates) == 1
        row = manifest.claim("worker-a", lease_seconds=60, max_attempts=3)
        assert row["status"] == "running"
        verify_immutable(row)
        mp4.write_bytes(b"modified")
        with pytest.raises(RuntimeError, match="immutable input"):
            verify_immutable(row)
    finally:
        manifest.close()


def test_manifest_reclaims_expired_lease_and_caps_attempts(tmp_path):
    source = tmp_path / "recordings"
    source.mkdir()
    (source / "sample.mp4").write_bytes(b"video")
    (source / "sample.srt").write_text("subtitle", encoding="utf-8")
    manifest = Manifest(tmp_path / "checkpoint.db")
    try:
        item = discover_candidates(source)[0]
        manifest.import_candidates([item])
        first = manifest.claim("worker-a", lease_seconds=0, max_attempts=2)
        second = manifest.claim("worker-b", lease_seconds=60, max_attempts=2)
        assert first["key"] == second["key"]
        manifest.record(item.key, "permanent_failed", last_error="bounded")
        assert manifest.claim("worker-c", lease_seconds=60, max_attempts=2) is None
    finally:
        manifest.close()


def test_error_classification_is_explicit():
    assert classify_error(TimeoutError()) == "timeout"
    assert classify_error(ConnectionError()) == "network"
    assert classify_error(RuntimeError("ffprobe artifact invalid")) == "artifact"
    assert classify_error(RuntimeError("bad request")) == "permanent"
    assert classify_error(RuntimeError("remote"), status_code=503) == "remote_5xx"
