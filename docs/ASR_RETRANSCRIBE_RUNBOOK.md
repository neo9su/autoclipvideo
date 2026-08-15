# Mandarin ASR retranscription runbook

The GPU service uses faster-whisper `large-v3` on the remote RTX 4080 SUPER.
The settings in `gpu_service_src/asr_config.py` explicitly select Chinese,
use the wig-commerce prompt, beam search, temperature fallback, VAD, and word
timestamps. SRT cue edges are taken from the first and last word timestamps,
which avoids carrying VAD padding into subtitle timing.

## Safe recording-level retry

Use the existing authenticated backend action for one recording only:

```text
POST /api/recordings/<recording_id>/retry-transcribe
```

It preserves the source MP4, replaces the recording SRT after the remote GPU
job completes, and then queues the normal classic/conservative editor. It does
not invoke director, creative, or Qianchuan pipelines. For a review-only ASR
run, pause the clip queue first and do not call any group-level regeneration
endpoint; after reviewing the new SRT, call the recording-level `reclip`
endpoint explicitly.

For sample #9931, verify the recording id from the backend database rather than
guessing it, save the old `.srt` before retrying, and compare cue boundaries and
text. The sample's conservative clip can then be regenerated with the existing
recording-level reclip endpoint. Do not run group-level director/creative
actions during validation.

## Rollback

To roll back ASR behavior, restore the previous values in
`gpu_service_src/asr_config.py` (`beam_size=5`, no word timestamps, and the
previous VAD values), redeploy the GPU service, and retry only affected
recordings. No database schema migration is required. Existing SRT files and
clips are not deleted by retranscription; operators should retain the saved
old SRT until the new clip is accepted.

The remote-only guard in `gpu_service_src/gpu_service.py` remains in place, so
ASR and heavy media processing cannot fall back to Mac/MPS execution.
