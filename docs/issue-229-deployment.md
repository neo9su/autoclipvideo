# Issue 229 deployment and rollback

## Deployment

1. Deploy the backend and GPU worker from the feature branch only after the pull request is approved.
2. Restart the backend service using the existing Windows service/process wrapper; do not reset, clean, or replace the production database.
3. Confirm the GPU worker health endpoint, then inspect the backend GPU status page.
4. Verify that a finished recording with its source video is uploaded, reaches completed transcription, has a non-empty SRT sidecar, and enters the clip queue.
5. Check that the final artifact contains the subtitle rendering and the generated voice-over mix. Keep the sample identifiers in the operator log only.

The worker remains GPU-only. Missing source video, missing SRT, empty SRT, and failed SRT download are terminally classified with an actionable reason, so they are not retried indefinitely. A later operator retry is safe after restoring the source because the existing missing-media retry policy recognizes these reasons.

## Rollback

1. Stop the backend through the existing service wrapper.
2. Revert the application deployment to the last approved revision; do not reset or edit business rows in the production database.
3. Start the backend and verify the health and GPU status endpoints.
4. If the previous revision is restored, existing terminal error classifications remain data-only diagnostics and can be retried through the normal operator workflow after the source is confirmed present.

No media files are deleted or rewritten by this change.
