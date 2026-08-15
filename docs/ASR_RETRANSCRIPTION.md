# Mandarin ASR retranscription

The remote GPU worker uses faster-whisper `large-v3` with CUDA fp16, explicit
Chinese language selection, beam size 8, word timestamps, VAD, and a Mandarin
wig-commerce prompt. `condition_on_previous_text=False` prevents a long live
stream from carrying an earlier hallucination into a later chunk. VAD padding
and silence thresholds are deliberately conservative so subtitle boundaries do
not grow across pauses.

## Isolated retranscription

`POST /api/recordings/{recording_id}/retranscribe` resets only the selected
recording's transcription state and wakes the normal remote-GPU upload loop. It
does **not** start clipping, director, creative, or Qianchuan work. After the
SRT has been checked, use the existing `POST
/api/recordings/{recording_id}/retry-clip` endpoint to regenerate that recording
with the current clip-engine setting.

For #9931, save the existing sidecar before retranscription, call the isolated
endpoint, wait for `transcribed=2`, compare the old and new SRT timestamps/text,
then call `retry-clip`. Validation should use the backend and GPU health
endpoints and must not run local heavy-media processing or enable Mac MPS.

## Rollback

The profile is defined in `gpu_service/main.py` and mirrored in
`gpu_service_src/gpu_service.py`. Roll back by restoring the prior
`beam_size=5`, VAD values, and removing the added prompt/timestamp options,
then restart only the remote GPU service. No database migration is required;
the endpoint uses the existing recording status columns. Existing SRT files
remain available as backups unless an operator explicitly replaces them.
