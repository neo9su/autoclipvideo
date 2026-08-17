# GPU host stability runbook

## Single-owner startup

`watchdog_agent.py` is the only process owner for GPU service (8877) and ComfyUI
(8188). Install `DouyinGPU-Watchdog` with `install_canonical_tasks.bat`. First
run `task_audit_and_apply.ps1` without `-Apply`; it exports the complete task
inventory and XML backups under `task-backups/<timestamp>`. After review, use
`-Apply` to disable only the named duplicate candidates. Rollback is:

```powershell
schtasks /change /tn <task-name> /enable
```

Do not run `start_all.bat` as another scheduled task.

## Evidence collection

Use `scripts/gpu_stability_audit.py` on the GPU host. It reads only the tail
(default 256 KiB) of each log, so a multi-GB `gpu.log` cannot cause an
out-of-memory scan. Example:

```powershell
python scripts/gpu_stability_audit.py --log gpu_service.log --log watchdog.log --whisper-pid 18396 --process-json whisper-process.json
```

Export `whisper-process.json` from Task Manager/PowerShell and correlate the
PID with the job database and recent log timestamps. The audit deliberately
reports `needs_job_correlation` and `do_not_kill`; it never terminates a
process without evidence of an orphaned job.

## Logs and health

GPU and watchdog logs rotate at 50 MiB with five backups by default. Override
`GPU_LOG_DIR`, `GPU_LOG_MAX_BYTES`, and `GPU_LOG_BACKUP_COUNT` on the GPU host.
`/health` now reports PID, start time, uptime, CUDA availability and queue data.
Watchdog `/status` persists restart counts, last exit codes, health and PID data
in `watchdog_state.json`. The control plane's 8899 status continues to probe
the remote health endpoint rather than treating stale watchdog cache as truth.

A healthy recovery check is five consecutive calls to
`http://127.0.0.1:8877/health` and `http://127.0.0.1:8878/status`, followed by
five calls to control-plane `/api/gpu/status`; each should show the current
remote PID and a fresh `health` probe. The macOS guard in
`gpu_service_src/gpu_service.py` and backend remote-GPU policy prevent local
media fallback.

## Disk-space admission

Transcription uploads retain `DISK_MIN_FREE_GB` of free space after the upload,
plus `DISK_UPLOAD_HEADROOM_GB` of working headroom for processing. Both values
are configurable GPU-service settings and default to 20 GB and 5 GB. The
service no longer requires the unrelated 100 GB data quota (or an 80 GB fixed
upload floor) to remain free before accepting a normal transcription upload.
Cleanup remains owned by the existing watchdog/service process and admission
checks do not delete recordings.
