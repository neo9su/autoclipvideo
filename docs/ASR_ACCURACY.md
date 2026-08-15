# GPU ASR configuration

The GPU transcription service uses faster-whisper `large-v3` with explicit Chinese
language, beam search, VAD, word timestamps, and a wig-commerce vocabulary prompt.
`condition_on_previous_text=False` prevents an earlier live-stream phrase from
being copied into a later chunk; VAD padding is intentionally modest so subtitle
ranges do not drift across silence.

## Retranscribe one recording

Use the backend endpoint with `regenerate_clip=false` for an SRT-only QA pass:

```text
POST /api/recordings/{recording_id}/retry-transcribe?regenerate_clip=false
```

After the GPU job completes, inspect the refreshed sidecar SRT. To regenerate a
conservative/realistic clip, call the normal retry-clip endpoint afterward. This
separation prevents validation from starting director, creative, or qianchuan
pipelines through the normal clip-completion hook.

## Rollback

Restore the prior values in `gpu_service/asr_config.py` (`beam_size=5`, the
previous VAD values, and omit the prompt/word timestamps if the deployed
faster-whisper build is incompatible), restart only the GPU service, then retry
the recording. Existing SRT sidecars and clips are not modified by a rollback;
keep a copy of the old SRT before replacing it. The change adds no database
columns or migrations.

ASR remains remote-only. `gpu_service/main.py` exits on macOS and the backend
continues to upload source media to the configured GPU service rather than
running heavy ASR locally.
