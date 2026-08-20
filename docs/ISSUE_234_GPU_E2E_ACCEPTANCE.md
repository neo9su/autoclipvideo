# GPU-only director E2E acceptance (Issue #234)

This runbook is a read-only acceptance procedure. It must use one group whose source MP4 and non-empty SRT are readable, whose transcription is complete, and whose director status is not successful. Do not rerun a successful video and do not mutate production rows to manufacture evidence.

## Evidence record

Record only these safe identifiers: `group_id`, `recording_id`, source/output basenames, UTC timestamp, deployed commit/version, remote job ID, and the GPU quality response. Do not record credentials, cookies, environment values, or host filesystem paths.

Required evidence fields:

- transcription: `transcribed=1`, source MP4/SRT readable, SRT has at least one timed cue;
- GPU policy: `execution_node=remote-gpu`, no local media fallback;
- subtitles: director job payload has timed `Dialogue:` entries and the GPU output is inspected at a cue timestamp with a frame image showing subtitle pixels;
- audio: generated voice file is playable, the GPU output has an AAC audio stream, and output duration is within 15–300 seconds;
- final playback: GPU `/director-jobs/{job_id}/quality` returns `ok=true`, one video stream and at least one audio stream.

The frame inspection and ffprobe/quality response are read-only checks against the downloaded artifact. Store the sanitized JSON and frame image in the deployment evidence store, not in the production database.

## Deployment

1. Deploy the control-plane commit and the matching GPU worker commit to the existing remote GPU service.
2. Verify the worker starts on the GPU host and the control plane still reports `execution_node=remote-gpu`.
3. Select the smallest eligible uncompleted group through a read-only query.
4. Run script generation, voice generation, and director composition once for that group.
5. Poll the remote job, fetch its quality response, and inspect a frame during a timed subtitle cue.
6. Attach the sanitized record to Issue #234 and retain the job ID and deployment version.

The control plane now refuses to submit a director job without timed subtitles or non-empty generated audio. The GPU worker rejects those requests, rejects source-audio fallback, burns subtitles, and exposes a stream/duration quality gate.

## Rollback

1. Stop new director dispatches using the existing deployment control, without changing completed production rows.
2. Roll back both control-plane and GPU-worker artifacts to the previous known-good version as a matched pair.
3. Confirm the remote GPU endpoint is healthy and `execution_node=remote-gpu`; do not enable local media processing.
4. Leave the acceptance group unmarked if the rollback happened before completion. Preserve the failed remote job ID and sanitized error for diagnosis.
5. Re-run acceptance only after a new deployment version is recorded.
