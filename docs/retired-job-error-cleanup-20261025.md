# Retired job error cleanup

Production cleanup used the existing `skip_reason = 已手动清除` marker, only for failed records with `local_deleted=1`, excluding running transcription/edit states. No status was changed to success; no recording row, group, source, subtitle or output was deleted.

Result: 469 additional historical transcription errors dismissed. Previously dismissed historical editing errors retained. Zero undismissed retired failures remain. 970 non-retired failed recording rows were preserved for further diagnosis/retry; their presence does not prove all are recoverable.

203 recovery directory:
`C:\Users\neo\douyin_backend\codex_rollbacks\dismiss-retired-errors-20261026-121304`

Contains full selected rows (`records.json`) and the exact cleanup/rollback script. Restore with that script using `--database C:\Users\neo\douyin_backend\douyin.db --restore <directory>\records.json`. Restore skips records whose execution state or errors changed since cleanup. No backend restart or GPU jobs were required.

Validation: SQLite transaction completed; remaining retired failure query returned zero. Targeted temporary-database test covers preserved source records, running-job exclusion, row retention and guarded restore. Historical counters that count failed states without the dismissal filter can still include archived failures; states were intentionally preserved.
