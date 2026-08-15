# ASR profile and rollback

The remote GPU worker uses `gpu_service/asr_config.py` for live-commerce Mandarin transcription. The default is faster-whisper `large-v3` with explicit Chinese language, beam search, temperature fallback, VAD padding, word timestamps, and a short wig-commerce vocabulary prompt. `condition_on_previous_text` is disabled to prevent cross-chunk drift; segment timestamps are written directly from faster-whisper's absolute offsets.

For a rollback, restart the GPU worker with `ASR_MODEL` set to the previously deployed model and restore the prior ASR tuning values (or revert `asr_config.py`). No database migration is required. The backend retranscription endpoint preserves an existing sidecar as `<recording>.srt.before-retranscribe` before queueing a new GPU job; compare it with the new sidecar and restore it manually if an operator chooses to roll back.

## Targeted retranscription

`POST /api/recordings/{recording_id}/retry-transcribe` is the deliberate, recording-scoped operation. It resets only that recording, wakes the existing remote-GPU poller, and lets the current `clip_engine` setting regenerate its clip after the new SRT arrives. It does not trigger director or qianchuan pipelines. Keep local-media execution disabled; ASR and media processing remain on the remote GPU worker.

Useful GPU-worker overrides (all optional): `ASR_MODEL`, `ASR_BEAM_SIZE`, `ASR_BEST_OF`, `ASR_CONDITION_ON_PREVIOUS_TEXT`, `ASR_VAD_THRESHOLD`, `ASR_VAD_MIN_SILENCE_MS`, and `ASR_VAD_SPEECH_PAD_MS`. The default profile is the accuracy-first setting for an RTX 4080 SUPER.
