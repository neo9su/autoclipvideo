# Resumable reclip batch and remote GPU evidence

`reclip_batch.py` is a control-plane runner for a deliberately staged rollout. It
only reads the source tree, writes a JSONL manifest and SQLite checkpoint, and
places all generated artifacts under a separate output directory. It does not
translate Mac, SMB, Windows, or container paths: `--source-dir` is the local
Mac input namespace and `--gpu-url` is the GPU HTTP service namespace.

## Read-only audit

The existing recorder/transcription queue is represented by `recordings` in the
SQLite database (`transcribed`, `synced`, `gpu_job_id`, `transcribe_error`,
`local_deleted`) and is polled by `backend/transcribe.py`. Existing upload
semantics use `X-Idempotency-Key`, three attempts, and a remote `/jobs` request;
the GPU service persists jobs and exposes `/jobs/{id}` and `/jobs/{id}/srt`.
Outputs from this workflow never use the recorder input directory. Existing
service startup and deployment evidence remains in `docs/REMOTE_MEDIA_DEPLOYMENT.md`.

## Proof-first procedure

```sh
# 1. Audit only: no GPU request and no source mutation
python scripts/reclip_batch.py --source-dir /path/to/recordings \
  --manifest audit/manifest.jsonl --checkpoint audit/checkpoint.db \
  --output-dir reclip-output --gpu-url http://gpu-host:8877 --scan

# 2. Run at most three real pairs, one at a time, after inspecting the manifest
python scripts/reclip_batch.py --source-dir /path/to/recordings \
  --manifest audit/manifest.jsonl --checkpoint audit/checkpoint.db \
  --output-dir reclip-output --gpu-url http://gpu-host:8877 --sample 3 \
  --rate-limit 2 --retries 3 --pause-file audit/reclip.pause

# 3. Pause safely, then resume by removing the pause file and rerunning the same command.
touch audit/reclip.pause
rm audit/reclip.pause
```

A sample run must be checked with `ffprobe` and the checkpoint's `evidence_json`:
its evidence includes source/output sizes, remote response, job ID, SRT hash,
ffprobe output, elapsed time, and failure classification. A `success` status is
not inferred from queue depth, `gpu_busy`, an old job, or a PR. The runner's
exit code is `0` when no permanent failures exist, `2` when permanent failures
remain, and `75` when another runner owns the lease.

## Recovery and safety

- The manifest key combines source and SRT content hashes, so restart is
  idempotent and detects source changes before upload.
- SQLite WAL checkpointing survives process interruption; a lease prevents two
  runners from consuming the same checkpoint. A stale lease requires explicit
  operator inspection/removal.
- Retryable transport/remote failures are bounded by `--retries`; missing,
  changed, unreadable, and invalid inputs are permanent failures. Pausing does
  not classify a job as success.
- The runner copies the source into an isolated output job directory only after
  the remote job is done, and downloads the generated SRT through the job route.
  It never deletes, overwrites, or edits files below `--source-dir`.
- The current GPU service accepts uploaded files and has no authentication
  contract in this revision. Do not expose it outside a private allowlisted
  network. A future remote-read API must add authentication, client/network
  allowlisting, basename/path traversal rejection, read-only source semantics,
  and request audit logging before deployment.

The remote SSH/deployment permission limitation remains an external blocker;
this workflow provides the minimum safe alternative: push-only upload over the
existing private GPU endpoint, with bounded retries and auditable evidence.
