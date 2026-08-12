# GPU Service Timeout & Reliability Fixes - Applied

**Date**: 2026-08-12 01:53
**Status**: ✅ DEPLOYED & VERIFIED

## Changes Applied to `gpu_service/main.py`

### 1. Job Timeout Wrappers
Added `asyncio.wait_for()` with explicit timeouts:

| Operation | Timeout | Code Location |
|-----------|---------|---------------|
| Transcription (`_run_with_lock`) | 900s (15 min) | main.py:401-408 |
| TTS Synthesis (`_do_tts_job`) | 1800s (30 min) | main.py:891-894 |

Both operations now properly release semaphores on timeout instead of blocking forever.

### 2. Stale Job Cleanup
Extended `_auto_cleanup_loop()` to evict stuck `processing` jobs older than 1 hour:

```python
_STALE_JOB_SECONDS = 3600  # 1 hour

# In cleanup loop:
stale = [jid for jid, j in list(store.items())
         if j.get("status") == "processing"
         and now - j.get("_created_at", now) > _STALE_JOB_SECONDS]
```

Evicted jobs are marked as `error` with message "Stale job evicted after 60min".

### 3. Timeout Error Handling
Added proper `asyncio.TimeoutError` exception handlers:

```python
except asyncio.TimeoutError:
    _log.error(f"TTS job {job_id} TIMED OUT after {_TTS_TIMEOUT}s")
    _tts_jobs[job_id].update({"status": "error", "error": err})
    _db_update_tts_job(job_id, status="error", error=err)
```

## Deployment Status

✅ Code deployed to GPU server (10.190.0.203) via scp
✅ GPU Service restarted (PID 9036, healthy)
✅ TTS test job completed successfully
✅ SSH tunnel stable (localhost:8877)
✅ Backend restarted (PID 53294, single process)

## Current System State

```
GPU Service: PID 9036, Uptime 2014s
  ├─ Health: healthy
  ├─ GPU: RTX 4080 SUPER, CUDA available
  ├─ Queue: depth=0, busy=False
  ├─ Jobs completed: 6780
  └─ Last test: TTS job done ✓

Backend: PID 53294
  ├─ Status: Running on port 8899
  ├─ Role: gpu-backend (media workers enabled)
  ├─ Clip queue: 1 running, 12 queued
  ├─ Director pipeline: Active (group 4717 in progress)
  └─ Poll state: Active (last poll just now)

Pending Transcription: ~70 recordings
  └─ Waiting for poll loop to process
```

## Known Issues (Non-Critical)

1. **Director pipeline failures**: Groups failing with `RemoteGpuRequiredError` during `merge_group`, `thumbnail generation`, and `final video postprocess` - this is EXPECTED in gpu-backend mode (local media execution disabled).

2. **One transcription error**: `Bad file descriptor` on recording 2_20260812_005846_001.mp4 - may need manual retry.

3. **MPS memory pressure**: sentence-transformers model loading occasionally fails due to MPS memory limits (9.05/9.07 GB). This affects director pipeline but not core transcription.

## Next Steps

1. Monitor transcription poll loop - should start processing the ~70 pending recordings
2. Consider setting `PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.0` to fix MPS OOM errors
3. Schedule periodic backend restart to prevent future stuck states

## Files Modified

- `/Users/claw/work/douyin-recorder/gpu_service/main.py` (2474 lines)
- New constants: `_STALE_JOB_SECONDS=3600`, `_TTS_TIMEOUT=1800`, `_TRANSCRIBE_TIMEOUT=900`

## Recovery Scripts Available

- `scripts/gpu-recovery.sh` - Automated GPU service recovery
- `scripts/recover-all.sh` - Full system recovery
- `scripts/deploy-gpu-admin.sh` - One-click deployment with admin endpoints
