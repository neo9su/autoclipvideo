"""Tests for the resumable batch control plane."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.reclip_batch import (Checkpoint, create_manifest, lease, scan_pairs,
                                  stable_job_key, validate_control_paths,
                                  validate_manifest_item, validate_output_root)


def test_manifest_uses_supported_sidecars_and_preserves_sources(tmp_path: Path) -> None:
    source_dir = tmp_path / "recordings"
    source_dir.mkdir()
    source = source_dir / "demo.mp4"
    sidecar = source_dir / "demo.mp4.srt"
    source.write_bytes(b"mp4-data")
    sidecar.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")
    original_source = source.read_bytes()
    original_sidecar = sidecar.read_bytes()

    manifest = tmp_path / "run" / "manifest.jsonl"
    assert create_manifest(source_dir, manifest) == 1
    record = json.loads(manifest.read_text(encoding="utf-8").splitlines()[0])
    assert record["job_key"] == stable_job_key(next(scan_pairs(source_dir)))
    assert record["source_size"] == len(original_source)
    assert source.read_bytes() == original_source
    assert sidecar.read_bytes() == original_sidecar


def test_checkpoint_seeds_idempotently_and_tracks_failures(tmp_path: Path) -> None:
    checkpoint = Checkpoint(tmp_path / "checkpoint.db")
    record = {"job_key": "key", "source": "/source.mp4", "srt": "/source.srt",
              "source_sha256": "a", "source_size": 7, "srt_sha256": "b", "srt_size": 3}
    checkpoint.seed(iter([record]))
    checkpoint.seed(iter([record]))
    assert checkpoint.counts() == {"pending": 1}
    job = checkpoint.next_job(retries=2)
    assert job and job["job_key"] == "key"
    checkpoint.update("key", status="permanent_failure", failure_class="input", failure_reason="bad input")
    assert checkpoint.counts() == {"permanent_failure": 1}
    checkpoint.close()


def test_checkpoint_claims_with_lease_and_requires_owner_for_success(tmp_path: Path) -> None:
    checkpoint = Checkpoint(tmp_path / "checkpoint.db")
    checkpoint.seed(iter([{"job_key": "key", "source": "/source.mp4", "srt": "/source.srt",
                          "source_sha256": "a", "source_size": 7, "srt_sha256": "b", "srt_size": 3}]))
    claimed = checkpoint.claim("worker-a", 60, 2)
    assert claimed and claimed["lease_owner"] == "worker-a"
    with pytest.raises(PermissionError):
        checkpoint.update("key", status="retry", lease_owner="worker-b")
    with pytest.raises(ValueError, match="complete GPU"):
        checkpoint.update("key", status="success", lease_owner="worker-a", evidence_json="{}")
    checkpoint.update("key", status="retry", lease_owner="worker-a", failure_reason="temporary")
    assert checkpoint.counts() == {"retry": 1}
    checkpoint.close()


def test_lease_rejects_second_runner_and_cleans_up(tmp_path: Path) -> None:
    lock = tmp_path / "run.lease"
    with lease(lock):
        with pytest.raises(FileExistsError):
            with lease(lock):
                pass
    assert not lock.exists()


def test_output_root_cannot_be_source_or_child(tmp_path: Path) -> None:
    source_dir = tmp_path / "recordings"
    source_dir.mkdir()
    with pytest.raises(ValueError):
        validate_output_root(source_dir, source_dir)
    with pytest.raises(ValueError):
        validate_output_root(source_dir, source_dir / "outputs")
    validate_output_root(source_dir, tmp_path / "isolated-output")


def test_control_plane_artifacts_and_manifest_inputs_are_isolated(tmp_path: Path) -> None:
    source_dir = tmp_path / "recordings"
    source_dir.mkdir()
    validate_control_paths(source_dir, tmp_path / "manifest.jsonl", tmp_path / "checkpoint.db")
    with pytest.raises(ValueError):
        validate_control_paths(source_dir, source_dir / "checkpoint.db")
    valid = {"source": str(source_dir / "a.mp4"), "srt": str(source_dir / "a.srt")}
    validate_manifest_item(source_dir, valid)
    with pytest.raises(ValueError):
        validate_manifest_item(source_dir, {"source": str(tmp_path / "outside.mp4"), "srt": str(source_dir / "a.srt")})
