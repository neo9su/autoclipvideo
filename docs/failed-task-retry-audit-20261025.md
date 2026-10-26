# Failed task triage and recoverable ASR results

Counts observed on 203:

- 36,068 failed clipping rows: 35,095 already marked `local_deleted=1`, 973 not marked deleted. Deletion flags are database state, not a fresh disk audit of every historical file.
- Of the 973: 401 `local media execution is disabled: clip variant N`, 149 `remote GPU clip job returned no output`, 84 `no clips selected`, 339 without a stored error.
- Non-deleted ASR failures: 23 no-speech results, three 600-second timeouts, three historical 3-second ffprobe timeouts.

Six screenshot rows (4969, 44602, 44603, 44615, 44618, 44621) were inspected as susun: source and SRT resolve successfully. Several MP4s are under room subdirectories whereas their SRTs are in the root. The current individual/bulk retry endpoints assemble paths directly instead of using the authoritative resolver, and dispatch the old editor/private GPU route. These were **not invoked**: source presence alone does not repair that execution path or verify hairstyle identity. A historical server log also records a private clip endpoint returning 404 MP4-not-found; this is one demonstrated no-output cause, not proof that all 149 share it.

AID profiles and snapshot were checked over verified TLS using the existing protected client configuration. The retry wrapper keeps the established stable idempotency keys. For candidate ASR rows it recovered existing successful scheduler jobs, rather than duplicating GPU work:

| recording | AID job | result |
|---|---|---|
| 44964 | 499 | Valid 266.828-second source and verified SRT; imported to its source sidecar and restored `transcribed=2` |
| 43090 | 501 | SRT recovered; actual source 21.610s; retained as evidence, not imported to the normal clipping flow |
| 43089 | 502 | SRT recovered; actual source 21.519s; retained as evidence |
| 43088 | 503 | SRT recovered; actual source 21.473s; retained as evidence |

45048 and 44947 are about 2700 seconds; the currently validated ASR client profile input limit is 1800 seconds. They remain deferred pending chunked audio support, not submitted with an invalid payload. Silent/no-speech files were not blindly retried.

## Actual mutation and rollback

Only recording 44964's successful ASR result was restored into production, after validating SHA-256, subtitle timestamps, source presence and unclaimed failed row state. Its clipping state remains failed; no clip was submitted and no external publication occurred. The source MP4 was unchanged. Original subtitle (if present) and full row were backed up with a conditional rollback refusing to overwrite subsequent processing:

`C:\Users\neo\douyin_backend\codex_rollbacks\aid-asr-restore-20261026-104654`

Evidence: `codex_operations\failed-retry-20261025`, including previous failed rows, per-recording scheduler states, retry decisions, screenshot source checks and restore result. Finite scheduled helpers are removed after completion. Four local regression tests cover BOM decoding, changed hashes, short sources, empty subtitles and out-of-bounds timestamps. Windows source restoration was verified in the DB after task exit 0. A Python 3.13 codec alias mismatch in the one-off importer was diagnosed and corrected to standard `utf-8-sig` before successful import.

## Still incomplete

No new GPU job was necessary for the four already successful ASR results. No failed clipping job was newly queued in this round. Retrying the 550 execution failures requires completing the AID clip-render adapter/path integration, then validating the available source/SRT/identity plan. No security policy was disabled, no direct/private GPU workload was submitted, no completed recordings were mass-reset, and historical failure records were not cleared to hide them. Earlier source patches still await a safe backend restart.
