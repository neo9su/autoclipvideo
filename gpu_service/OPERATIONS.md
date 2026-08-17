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

Export `whisper-process.json` from Task Manager/PowerShell and correlate the PID
with the job database and recent log timestamps. The audit deliberately reports
`needs_job_correlation` and `do_not_kill`; it never terminates a process without
evidence of an orphaned job.

## Logs and health

GPU and watchdog logs rotate at 50 MiB with five backups by default. Override
`GPU_LOG_DIR`, `GPU_LOG_MAX_BYTES`, and `GPU_LOG_BACKUP_COUNT` on the GPU host.
`/health` now reports PID, start time, uptime, CUDA availability and queue data.
Watchdog `/status` persists restart counts, last exit codes, health and PID data
in `watchdog_state.json`. The control plane's 8899 status continues to probe the
remote health endpoint rather than treating stale watchdog cache as truth.

Disk cleanup runs periodically and before rejecting work. Configure the reserve with
`DISK_MIN_FREE_GB` (default `20` GB); it is the free space retained after an
upload, not a required 80/100 GB batch size. `DISK_QUOTA_GB` and
`DISK_GUARD_GB` continue to control cleanup of generated outputs.

For the canonical Windows deployment, update the service environment through
the watchdog-owned service configuration and restart only that service. Do not
start a second copy with `start_all.bat`.
