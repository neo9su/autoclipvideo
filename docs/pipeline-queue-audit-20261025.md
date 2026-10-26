# Queue audit and statistics correction

Observed on 203, October 25 Edmonton time:

- The 310 alleged clip-pending records all have `local_deleted=1`. No eligible clip backlog was established. The public stats query omitted the file-deletion and finished-recording conditions; do not revive deleted records or mass retry them.
- Production subsequently advanced: recording 45411 entered merge, with three durable transcription job IDs stored and 42 further recordings awaiting transcription. Zero running at an earlier snapshot was not proof of a permanent dispatch failure.
- Three monitored rooms updated their check timestamps, with no recent room errors and all reported offline. This confirms polling, not independent verification of the broadcasters' true live state.
- 49 non-deleted recording rows lack end times. At least recording 45416 was rejected by the existing validator (`moov atom not found`). No source files were deleted, no end times guessed, and no corrupted files marked valid.
- Historical creative retries include groups without eligible source material. Latest Qianchuan failures include insufficient shot/script matching and missing usable clips; these remain unresolved, not fixed by changing queue counters.

## Applied source repair

`scripts/patch_pipeline_stats.py` changes only `get_stats`'s clip-pending CASE expression, adding `local_deleted=0` and a non-null end time. All historical failure counts retain their meaning. `scripts/stage_pipeline_stats.py` backs up the server's actual main.py and writes a SHA-guarded rollback, then atomically updates source without overwriting local unrelated work.

Production backup: `C:\Users\neo\douyin_backend\codex_rollbacks\pipeline-stats-20261026-100345`.

The backend was **not restarted** while clip/transcription tasks were active. Until a safe desktop-backend restart, the existing process may continue reporting 310. No GPU service restart, source deletion, DB status modification, external publication, or task retry was performed.

## Verification and rollback

Targeted SQLite regression test: one passing test covers deleted, unfinished, valid pending and completed records, plus patch drift rejection. Python compilation runs before source replacement. Rollback script checks the current and saved source hashes before restoring. Activate/revert only when publication and local media work are idle; preserve durable transcription job IDs and all recordings/groups.
