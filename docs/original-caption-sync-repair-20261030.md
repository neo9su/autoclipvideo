# Original-audio variant caption repair

Reported example: group 5595, 刘海假发 浅棕 (displayed as 刘海 浅棕 长直发). Its source recording is 45497 / 1_20261029_234807_004.mp4. The user also reports both styles affected across sampled groups.

## Confirmed production defects

The live editor passes merged/split selection scenes to subtitle generation, losing original sentence timing. `build_ass` truncates every scene to 14 characters. It also positions an incoming faded segment's subtitles at the prior segment's end rather than its actual start. The legacy clip idempotency key excludes subtitle content, allowing reuse after a caption-only correction. Variant output paths share the room's sequence allocation before their final version-specific copies are made.

The variant pipeline currently selects original recordings and requests original audio. It does not directly select the director/creative TTS track. This code inspection does not establish what audio is present in an older artifact; no listening or complete playback comparison has been completed. The source SRT contains recognition errors, which this timeline repair does not correct.

## Prepared changes

- Production-compatible, AST-scoped patch preserves raw source cues for realistic/conservative rendering while keeping selection/scoring scenes separate.
- Complete text wraps at 14 characters instead of truncating; preserves existing styling and text sanitization.
- Incoming transition timing is rebased correctly.
- Caption SHA256 participates in the original-audio variant idempotency key.
- Per-version/per-group editor output namespaces prevent concurrent filename collisions.
- The local editor already preserves raw cues; its incoming transition offset was corrected too.

19 targeted tests cover complete original cue text/timestamps, overlap/cuts, safe ASS escaping, cache invalidation wiring and refusal to activate while publication/editing is active. Production source syntax compilation passed. No GPU render was submitted, and existing video files have not been replaced or regenerated.

## Deployment state — staged, NOT active

203 stage:
`C:\Users\neo\douyin_backend\codex_operations\original-caption-sync-20261030`

Backup and candidate files:
`C:\Users\neo\douyin_backend\codex_rollbacks\original-caption-sync-20261030-211546`

The directory contains full original editor/transcribe sources, patched candidates, SHA256 manifest and guarded rollback.py. Neither production source nor the running backend has been replaced. Activation is deliberately guarded against active publishing, clip jobs, realistic/conservative jobs and other rendering statuses; older stale statuses need diagnosis rather than blindly clearing them.

Publication 12421 and new style generation were active during investigation. Finish publication and inspect/drain active editing before running the staged activate_original_caption_sync.py with the backup path. It preserves the existing susun desktop launcher and does not restart GPU services or alter media/database rows. Activation still needs live HTTP checks, followed by one scheduler-supported real video regeneration and complete audio/subtitle playback review before any historical batch rerender. Existing 203 AID renderer's rich subtitle capability was not established by merely listing profiles; do not bypass the scheduler through the legacy private worker ports.

## Activation follow-up

After the user completed publication, a finite drain check waited for active styles and other editing to finish. The first wait expired without changing production; a subsequent idle check passed and the prepared repair was activated. Only the susun desktop backend restarted (new PID 22400, Session 2). Editor and transcribe hashes match the staged candidates. GPU process PID 12684 was unchanged.

Post-activation HTTP checks passed: rooms 5 (0.05s), products 409 (0.08s), groups 1312 (15.57s). These counts advanced naturally since the earlier checks; no business rows were explicitly edited by the deployment.

An isolated CPU-only validation loaded the deployed editor and the reported source recording 45497 SRT (1838 original cues). Two cut windows produced exactly 16 expected original subtitle events (16 actual), without selection-scene text. The ASS and validation JSON are stored under the operation stage. This confirms deployed caption mapping, not complete audible playback of a remade video. Existing finished artifacts remain unchanged and still need scheduler-compatible regeneration and full review.

GPU diagnosis: AID reported gpu-203 ONLINE; the same legacy GPU service process remained alive. Health requests intermittently timed out (5s and 8s), but subsequent calls returned healthy/CUDA available in 0.18s and 0.05s. Worker logs and read-only process inspection showed ongoing/completed editing and TTS. No GPU restart was performed. The cause of intermittent timeouts has not been conclusively isolated; do not claim it is permanently fixed.
