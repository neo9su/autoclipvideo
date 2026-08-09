# Resumable re-edit batch (Issue 130)

`scripts/resumable_reclip.py` is a control-plane batch coordinator. It is safe to run in inventory-only mode before any remote work:

```bash
python scripts/resumable_reclip.py \
  --source-root /path/to/recordings \
  --state-dir /path/to/reclip-state
```

This creates an append-only JSONL manifest, SQLite checkpoint, and JSONL audit log. It discovers only non-empty, same-stem MP4/SRT pairs and does not open sources for writing. The item key is derived from the canonical input path and MP4 SHA-256, so a changed source is a new item rather than an overwrite.

## Controlled remote contract

Only start processing after the remote GPU team exposes an authenticated, allow-listed endpoint:

```bash
python scripts/resumable_reclip.py \
  --source-root /path/to/recordings \
  --state-dir /path/to/reclip-state \
  --endpoint https://gpu.example/reclip-jobs \
  --limit 3 --max-attempts 3 --interval 2
```

The endpoint receives JSON containing `idempotency_key`, source metadata, and `output_policy: isolated`. A successful response must be `2xx` and include `job_id` plus `output.mp4_path` and `output.srt_path`; otherwise the item is not successful. The endpoint must enforce authentication, source-root allow-listing, read-only source mounts, isolated output storage, and return GPU-side ffprobe/readability evidence with the job response. The coordinator classifies transport and 408/425/429/5xx failures as retryable, caps attempts, and returns exit code 2 when retries or permanent failures remain. Exit code 3 means the lease is held by another process.

The coordinator never treats queue depth, GPU occupancy, an old job ID, or a PR as completion evidence. A remote adapter should preserve the returned request/response, job ID, output paths, output byte sizes, MP4/SRT readability and ffprobe evidence in the response and event log.

## Paths and blocker policy

Keep these namespaces distinct in manifests and logs:

- Mac source path: local control-plane input path.
- SMB/Windows path: an explicitly configured read-only share path; never inferred or substituted.
- GPU service path: remote path returned by the service; never presented as a Mac path.

Do not launch a large batch until an end-to-end proof has completed for three real recordings, including the known 7080 failure case. If SSH/deployment access remains unavailable, the minimum safe alternative is a separately deployed authenticated HTTP adapter on the GPU host; do not expose a raw file browser or accept arbitrary paths.
