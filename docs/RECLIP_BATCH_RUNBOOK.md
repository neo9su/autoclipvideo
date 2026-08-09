# Resumable full-library reclip runbook

`backend/reclip_batch.py` and `scripts/reclip_batch.py` provide the safe control-plane foundation for issue #130.

## Safety contract

- The source tree is read-only by convention and is protected by a manifest-time size/SHA-256 snapshot plus a pre-job `verify_immutable` check.
- Outputs must be outside the source tree. Each item is keyed by the source paths, sizes, and hashes; rerunning the planner is idempotent.
- SQLite uses WAL, an atomic claim, an expiring lease, attempt counts, and an event log. Expired workers can be reclaimed, while callers cap attempts and classify errors as `network`, `remote_5xx`, `timeout`, `artifact`, or `permanent`.
- A job is not successful merely because a queue, slot, `gpu_busy`, or historical job exists. A future GPU adapter must record the job ID, HTTP request/response, exit code, output MP4/SRT paths and sizes, ffprobe/readability evidence, and GPU-side consumption evidence before calling `Manifest.record(..., status="succeeded")`.

## Plan a bounded proof batch

This command only scans and checkpoints; it does not submit GPU work:

```bash
python scripts/reclip_batch.py \
  --input /path/to/recordings \
  --output /path/to/reclip-output \
  --manifest /path/to/reclip-output/manifest.sqlite \
  --max-items 3
```

The output directory must not be the source directory or a child of it. Start with three real MP4/SRT pairs, including the known 7080 failure if its immutable source pair is present. Preserve the JSON output and manifest event rows as the audit record. Only after the proof has three complete evidence chains should an operator add a reviewed remote-GPU adapter.

## Remote path rules and current blocker

Keep these values separate in any adapter:

1. Mac source path: local filesystem path used for read-only hashing/upload.
2. SMB/Windows path: remote storage path, only when the operator has verified that exact path and read semantics.
3. GPU service URL: HTTP endpoint, never a filesystem path.

At the time of this change, the remote backend does not expose the required versioned API, and SSH deployment permission is unavailable. The minimum safe alternative is to deploy the adapter/service through the authorized remote operator, with an allow-listed input root, read-only source mount, authentication, request size/rate limits, and isolated output root. Do not fabricate a Windows path or point the service at an unverified SMB location. Do not start a 1.3 TiB run until that blocker is cleared and the three-item proof is archived.

## Resume, pause, and monitoring

Rerun the planner against the same manifest to resume discovery. An adapter should stop claiming new rows when paused, renew leases only while actively working, and emit an alert when the service is unreachable, a lease expires, or a row reaches its retry cap. `Manifest.counts()` is the authoritative progress summary; legacy queue/slot state is informational only.
