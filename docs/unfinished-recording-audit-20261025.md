# Interrupted-recording follow-up (October 25, Edmonton)

## Verified data recovery

A single read-only audit ran as `susun`, the account that can access migrated recording media. It examined all 49 non-deleted rows without end times:

- 14 files had a readable video stream, finite duration, and unchanged size/mtime across two observations.
- 34 ffprobe calls exceeded the bounded 12-second inspection limit. These are **not proven corrupt** and were preserved without changing their rows.
- One source could not be located/accessed, including latest row 45423. No deletion was performed.

A second one-off operation restored end metadata only for the 14 stable HD files, after checking age, unchanged bytes/mtime, absence from active recorder filenames, and that rows were unclaimed/unprocessed. End times were derived from stored recording start plus measured file duration, not the current wall clock. All rows were rechecked under one transaction before updating. End time, size, duration, duration status and skip reason were the only fields changed. Source files were not changed. Remaining unfinished rows: 35.

Recovered IDs: 45420, 45368, 45358, 45357, 45312, 45293, 45292, 45290, 45288, 45269, 45225, 45125, 45124, 45104.

Backup and guarded rollback: `C:\Users\neo\douyin_backend\codex_rollbacks\unfinished-metadata-20261026-101724`. The rollback refuses to undo rows after production processing has advanced. One-off audit/recovery scheduled tasks were removed after completion; evidence remains in `codex_operations\pipeline-audit-20261025`.

## Source preservation repair

Production `_finalize_segment` previously called `os.unlink` for every non-accepted probe result, including absent/unavailable duration. This could discard a source merely because media probing failed. It now returns without deletion or a rejected/deleted callback for `duration_unavailable`. Existing confirmed-short-segment handling is unchanged.

Production source backup: `C:\Users\neo\douyin_backend\codex_rollbacks\recorder-preservation-20261026-101447` (includes hash-guarded rollback). **Activation still requires a safe desktop-backend restart; the running process was not interrupted while production was busy.** Earlier stats/retry patches likewise remain staged.

Tests: six local focused checks (five invalid-probe cases plus recovery eligibility); five additional recorder checks passed against actual patched server source in an isolated process and temporary directory. The ordinary local recorder test collection could not import unrelated `httpx` in the lightweight test environment; no packages were reinstalled. Full recorder checks instead ran successfully on 203, where that dependency exists.

## Production result and unresolved issues

Group 5473 completed classic/director/creative, but its Qianchuan attempt failed again with missing catalogue-style evidence. Group label/product keyword is only `卷发`, wig color is null; an arbitrary choice among cart candidates would not establish product identity. Do not report this as a publish-ready Qianchuan success. Existing recording command already uses fragmented MP4 (`frag_keyframe+empty_moov+default_base_moof`), so no speculative muxer change was made.
