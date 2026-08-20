# Issue #229 deployment and rollback notes

## Deployment

1. Deploy the feature branch/PR to the backend control-plane service only after review; keep the existing GPU-only execution policy and the existing Windows recording storage mount unchanged.
2. Restart the backend service using the normal deployment procedure. Do not reset, vacuum, or overwrite the production SQLite database.
3. Confirm `/api/gpu/status` reports a recent `poll_state.last_poll_at`. For a known finished recording with an available source MP4, `last_submit_at` should advance after the poll loop wakes.
4. Verify one non-successful historical row with a missing MP4 or empty/missing SRT is moved out of the pending queue with a clear `transcribe_error`/`skip_reason`. This is a terminal classification, not a database repair; restoring media later requires the existing explicit retry endpoint.
5. For an end-to-end sample, verify the recording reaches `transcribed=2`, a non-empty SRT sidecar exists, and the generated clip/final video and voiceover artifacts are present. Do not re-run rows already marked successful.

The fix accepts both supported sidecar layouts (`source.srt` and `source.mp4.srt`) and does not translate Windows host paths in the control plane. Chunk rows created by the remote-upload preparation path remain ordinary GPU transcription jobs.

## Rollback

1. Stop or roll back the backend service to the previously reviewed release; do not stop the GPU service unless the deployment procedure requires it.
2. Leave recording files and database rows untouched. In particular, do not reset terminal `transcribed=-1` rows or successful output rows as part of rollback.
3. If a source is restored, use the existing explicit retranscription/retry workflow after confirming the storage mount and SRT naming. The older release may again show restored missing-source rows as pending until manually handled.
4. Re-check `/api/gpu/status` and logs after rollback, ensuring no local media processing was enabled.
