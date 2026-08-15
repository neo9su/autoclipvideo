# Mandarin ASR configuration

Remote transcription runs `faster-whisper` `large-v3` on the GPU service. The
backend sends `language=zh`, beam search, temperature fallback, a wig-commerce
initial prompt, and word timestamps. `condition_on_previous_text` is disabled
by default so a live-stream recognition error does not cascade into later
subtitles. VAD uses speech padding and a conservative silence window to reduce
subtitle drift at chunk boundaries.

## Retranscription

`POST /api/recordings/{recording_id}/retranscribe` queues one recording for a
fresh GPU transcription. If an SRT exists, it is preserved as
`<recording>.srt.previous.srt` before the recording is reset. The endpoint only
resets that recording and does not schedule director, creative, or Qianchuan
pipelines. After the GPU job completes, the normal clip queue regenerates the
recording's clip from the new SRT.

## Configuration and rollback

The defaults are in `gpu_service/asr_config.py`. Operators can override the
model and decoder settings with the `ASR_*` environment settings used by the
GPU service. To roll back, restart the GPU service with the prior values (or
remove the overrides to return to the checked-in defaults); no database
migration is required. Restore the `.previous.srt` sidecar manually if a
retranscription must be reverted before rerunning the clip.

The GPU service remains remote-only. Do not run ASR or media processing on the
Mac control plane, and keep the existing local-media guard enabled.
