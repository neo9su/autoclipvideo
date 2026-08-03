# Media storage and SMB isolation

The Mac application is a control plane. `recordings/` contains upload staging and
control-plane result copies; `gpu_storage/` is a remote GPU-service data root and
must not be exposed by the Mac SMB server. They are not a processing share:
`recordings/` is read only for control-plane upload/download, while the actual
media work and GPU-side temporary files live under the remote node's
`gpu_storage/`. Video processing, ffmpeg, ASR, TTS, analysis, and quality checks
run on the remote GPU node only.

## Recommended macOS isolation

- Do not share the repository, `recordings/`, `gpu_storage/`, or any parent folder
  in System Settings → General → Sharing → File Sharing.
- If an SMB share is required for unrelated work, use a separate directory outside
  the repository and grant access only to the intended account.
- Keep `recordings/` and `gpu_storage/` out of the shared directory tree; moving or
  renaming a folder is not sufficient if an ancestor remains shared.
- Verify the File Sharing list after deployment and remove stale share points.
- Prefer the GPU service HTTP API for job upload/download; do not use SMB, rsync,
  or scp as part of a job.
- Keep result downloads bounded and idempotent: download a completed artifact
  once, record its byte count, and reuse the existing local result on retries.
- If a job cannot reach the GPU, leave it queued with `execution_node=remote-gpu`
  and `gpu_waiting=1`; never start a local worker to drain the queue.

The application cannot disable macOS SMB shares safely from code because that is a
host-level administrative setting. This document is the deployment boundary and
prevents the workflow from treating a shared folder as a processing fallback.
