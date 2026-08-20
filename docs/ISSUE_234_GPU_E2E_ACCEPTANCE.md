# Issue 234 GPU-only director E2E acceptance

This runbook defines a small, auditable acceptance sample for the director
pipeline. It does not re-run a successful video and does not update production
database state as a repair. The sample must be a group whose source MP4 and
non-empty SRT are readable, transcription is complete, and the director output
has not previously been marked successful.

## Evidence record

Copy this record into the deployment change log after a real GPU run. Use the
repository revision and deployment timestamp; do not include credentials or
host-local absolute paths.

| Field | Value |
| --- | --- |
| Group ID | `<group-id>` |
| Recording ID(s) | `<recording-id>` |
| Source MP4 / SRT | `<media filename>` / `<subtitle filename>` |
| Transcription state | `completed` |
| GPU job ID | `<director-job-id>` |
| Deployment revision | `<git revision or image digest>` |
| Started / completed (UTC) | `<timestamp>` / `<timestamp>` |
| Final artifact ID | `<artifact identifier>` |

The evidence bundle must contain read-only output from the remote GPU quality
endpoint and frame inspection:

- source and SRT existence/readability, with at least one timed cue;
- remote `quality` response showing one video stream, one audio stream, a
  positive duration, and duration at least 30.5 seconds;
- a decoded frame from a cue interval showing the burned subtitle text;
- audio decode/playability and the final video audio stream metadata;
- the voiceover artifact metadata and a statement that it is muxed into the
  final artifact.

The Mac control plane must only submit/download artifacts. Do not run ffmpeg,
ffprobe, local ASR, local TTS, or local composition for acceptance. ffprobe and
frame extraction belong on the GPU worker; retain their sanitized output in the
evidence bundle.

## Deployment

1. Deploy the backend and GPU worker from the reviewed revision.
2. Verify the worker reports the expected revision and the remote GPU execution
   node is reachable.
3. Select the smallest eligible group using read-only queries. Do not alter
   success/status columns to make it eligible.
4. Submit the director workflow once, record the group/recording/job IDs and
   timestamps, and wait for the remote quality gate.
5. Save the sanitized quality response and visual/audio checks with the record
   above. Leave the production state unchanged if any check fails.

## Rollback

If the acceptance fails, stop new director submissions, preserve the job error
and evidence bundle, and redeploy the previous reviewed revision. Do not mark a
failed artifact successful and do not delete the source sample. After rollback,
re-run the same read-only quality checks against existing artifacts only; a new
acceptance run requires an explicit change record.

The product now fails the director job before encoding when ASS dialogue or TTS
audio is missing. It also rejects a downloaded result unless the GPU quality
endpoint confirms video and audio streams and publish-safe duration. This keeps
subtitle and voiceover failures visible rather than producing a silent or
unsubtitled success.
