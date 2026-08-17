# Short recording cleanup

The processing floor is **28.0 seconds inclusive**. A 27.99-second recording
is `too_short` / `时长不足`; 28.0 seconds is accepted. Missing, unreadable, or
invalid duration probes are `duration_unavailable` and are never deletion
candidates.

## Dry-run inventory

Run against the active backend's mounted database and recordings directory:

```sh
python scripts/inventory_short_recordings.py --db /path/to/douyin.db --recordings-root /path/to/recordings --output short-recordings.json
```

The command is read-only and reports recording ID, path, duration, size, and
total reclaimable bytes. No existing file is deleted by this task.

## Later approved deletion

After an operator reviews the JSON report and explicitly approves the listed
IDs, use a separately reviewed deletion operation (not the dry-run command):

```sh
python scripts/delete_short_recordings.py --db /path/to/douyin.db --recordings-root /path/to/recordings --ids <approved-id-1>,<approved-id-2> --confirm
```

That command/endpoint is intentionally not implemented or invoked here; the
explicit confirmation gate must remain separate from inventory.
