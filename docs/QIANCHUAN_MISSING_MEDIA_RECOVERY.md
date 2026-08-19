# Qianchuan missing-media recovery (4675–4684, 4687)

The affected groups are **4675–4684 and 4687**. Their source recording IDs are **20204–20213 and 20217**. Groups 4685, 4686, and 4688–4694 are intentionally out of scope and must not be retried.

## Diagnosis (safe by default)

Run the read-only diagnostic against the backend database and the backend's mounted recordings directory:

```bash
python scripts/diagnose_qianchuan_missing_media.py \
  --db <backend-database> \
  --storage-root <backend-recordings-mount>
```

The command opens SQLite in `mode=ro`, does not call the backend/GPU services, does not update group or queue state, and checks each source MP4 plus its readable SRT sidecar. Use `--groups` only when narrowing the inspection; do not include successful groups in a recovery command.

## Operator prerequisite

If the report says `ready: false`, the failure is missing media in the backend storage namespace, not a Qianchuan composition bug. Locate the original source recording and transfer it through the existing operator-controlled `sync_mp4_to_storage` procedure so that the backend can see the exact database `filename` below its storage mount. Preserve the filename and provide the corresponding non-empty `.srt` sidecar (`<filename>.srt` or `<filename-without-mp4-extension>.srt`). Do not fabricate an MP4, rewrite database paths, delete rows, or change `qianchuan_status` manually.

Re-run the diagnostic until every required source reports both `mp4.readable: true` and `srt.readable: true`. Create the normal operational database backup **before** any subsequent state-changing retry. After the prerequisite is verified, an operator may retry only the affected groups through the existing Qianchuan recovery path, in a small batch that respects the active queue; successful groups remain untouched.

If the source cannot be recovered, stop and retain the diagnostic report. The application cannot safely generate a truthful Qianchuan video without the original media.
