# Short recording cleanup

The backend uses one inclusive threshold: recordings with a probed duration `< 28.0` seconds are `too_short`; exactly `28.0` seconds is eligible. Missing or invalid media is `duration_unavailable` and is never deletion-eligible.

## Dry-run inventory

Run from the repository root:

```sh
python scripts/inventory_short_recordings.py > short-recording-inventory.json
```

This only probes media and prints recording IDs, relative paths, durations, sizes, and total reclaimable bytes. It does not modify the database or delete files.

The checked-in `short-recording-inventory.json` is the verified dry-run against the
repository's active local database snapshot at implementation time. It found zero
verified `< 28.0s` files and therefore reports zero reclaimable bytes. An unavailable
probe is deliberately not counted as reclaimable.

## Approved cleanup (later, explicit operator action)

There is intentionally no automatic deletion endpoint in this change. After reviewing the dry-run report and explicitly approving each recording, an operator may delete an explicitly approved set with the existing authenticated endpoint, one ID at a time:

```sh
curl -X DELETE "$BACKEND_URL/api/recordings/<recording_id>/local-file"
```

The endpoint is `DELETE /api/recordings/{recording_id}/local-file`; it requires the
recording to be synced and not actively processing. No cleanup command or endpoint
is run by this task.

Do not substitute an inventory query for operator confirmation. Verify the active remote backend first with `deploy/verify-remote.sh <backend-url>` and run the inventory against that backend's database/media mount.
