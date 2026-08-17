# Short recording cleanup

The backend uses one inclusive threshold: recordings with a probed duration `< 28.0` seconds are `too_short`; exactly `28.0` seconds is eligible. Missing or invalid media is `duration_unavailable` and is never deletion-eligible.

## Dry-run inventory

Run from the repository root:

```sh
python scripts/inventory_short_recordings.py > short-recording-inventory.json
```

This only probes media and prints recording IDs, relative paths, durations, sizes, and total reclaimable bytes. It does not modify the database or delete files.

## Approved cleanup (later, explicit operator action)

There is intentionally no automatic deletion endpoint in this change. After reviewing the dry-run report, an operator may delete an explicitly approved set with the existing authenticated endpoint, one ID at a time:

```sh
curl -X DELETE "$BACKEND_URL/api/recordings/<recording_id>/local-file"
```

Do not substitute an inventory query for operator confirmation. Verify the active remote backend first with `deploy/verify-remote.sh <backend-url>` and run the inventory against that backend's database/media mount.
