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

## #9931 validation evidence (2026-08-15)

The first-choice `large-v3` path was exercised against recording `9931` using
the recording-level retry endpoint. Before the retry, the existing SRT and
conservative clip were copied to an operator-controlled backup location. The
request was accepted and reset the row to the normal upload queue
(`transcribed=0`, `synced=0`); no group-level pipeline request was made.

The comparison could not be completed from this control-plane session: the
backend stopped responding while the recording was waiting in the existing
transcription backlog, so no new SRT or regenerated clip was available to
inspect. The remote GPU health probe recovered and reported healthy CUDA on an
RTX 4080 SUPER with an empty GPU queue, but that does not prove the recording
job completed. Treat #9931 as **pending validation**, not as a claimed accuracy
win. The original SRT/clip backup remains the rollback artifact.

The implementation-side benchmark is deterministic once the backend poller is
healthy: record the old/new cue count, transcript text diff, and the first/last
word-to-cue boundary deltas, then inspect the regenerated MP4 with preserved
audio. Do not report visual alignment improvement without those artifacts.

## Alternative model comparison

`Qwen3-ASR-1.7B` and `FireRedASR-AED` (1.1B) were not switched into production
or silently installed on the GPU host. This checkout has no adapter for either
model's inference/API output, tokenizer, or SRT timestamp contract, and the
remote host is offline by policy for model downloads. A fair comparison needs
the exact pinned model files, an isolated GPU job mode, and the same #9931 audio
plus cue-delta report. Until those prerequisites exist, the concrete blocker is
**missing deployable model/runtime and benchmark adapter**, not an accuracy
claim. Keep `large-v3` as the production baseline; add each candidate behind an
explicit model setting and isolated output directory before comparing.

## GPU deployment

1. Copy `gpu_service_src/asr_config.py` with the GPU service source (or deploy
   the repository revision containing it) to the Windows GPU host.
2. Confirm the `large-v3` model is already present in the local model cache;
   do not enable online downloads on the production worker.
3. Restart only the canonical GPU service/watchdog owner, then verify
   `GET /health` reports CUDA and `GET /api/gpu/status` reports the remote GPU
   healthy. Do not restart the Mac control-plane media worker.
4. Queue only recording `9931`, save its old SRT/clip, and wait for
   `transcribed=2` before invoking recording-level conservative reclip.
5. Capture old/new SRT and clip paths plus the health response in the validation
   record. Never invoke director, creative, or Qianchuan group endpoints for
   this test.

## Rollback

To roll back ASR behavior, restore the previous values in
`gpu_service_src/asr_config.py` (`beam_size=5`, no word timestamps, and the
previous VAD values), redeploy the GPU service, and retry only affected
recordings. No database schema migration is required. Existing SRT files and
clips are not deleted by retranscription; operators should retain the saved
old SRT until the new clip is accepted.

The remote-only guard in `gpu_service_src/gpu_service.py` remains in place, so
ASR and heavy media processing cannot fall back to Mac/MPS execution.
