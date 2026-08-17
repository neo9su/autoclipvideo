# Short recording cleanup

The inclusive source threshold is 28.0 seconds: `< 28.0` is `too_short`, and
`28.0` is accepted. Missing or invalid probes are `duration_unavailable`, are
excluded from processing, and are never counted as reclaimable.

## Verified dry run

```sh
python scripts/inventory_short_recordings.py --db douyin.db --recordings-dir recordings > short-recording-inventory.json
```

The command reports recording IDs, paths, durations, sizes, and total
reclaimable bytes without modifying the database or deleting files. Run it
against the active backend/database mount before approving cleanup.

## Explicit cleanup later

No automatic cleanup is part of this change. After reviewing the report and
explicitly approving a recording, use the existing authenticated endpoint one
recording at a time:

```sh
curl -X DELETE "$BACKEND_URL/api/recordings/<recording_id>/local-file"
```

This task does not invoke that destructive endpoint.
