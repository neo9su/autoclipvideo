# Mandarin ASR and subtitle alignment

The remote GPU worker uses faster-whisper `large-v3` with CUDA `float16` by
default.  The RTX 4080 SUPER deployment runs one transcription at a time to
avoid VRAM contention.  Mandarin is explicit (`zh`), beam search is 8, VAD is
enabled with a 350 ms silence split and 400 ms speech padding, and fallback
temperatures are enabled.  `condition_on_previous_text=False` prevents a live
stream's previous sentence from pulling a later sentence or chunk off course.
Word timestamps are requested so future subtitle post-processing can refine
boundaries without changing the source-audio clock.  Domain terms are supplied
through Whisper's `initial_prompt` (假发, 刘海, 鬓发, 头顶, 颅顶, 发际线, 黑长直,
自然黑, 方圆脸, 显脸小, 真人发, 高温丝).

## Safe one-recording validation

From the repository root, after confirming the GPU and backend health endpoints:

```bash
python scripts/retranscribe_recording.py --recording-id 9931 --diff
```

The tool backs up the existing sidecar as `.before-asr`, uploads only that
recording to the remote GPU, and writes the returned SRT next to the source.
It does not reset a batch, run local ASR, or trigger director/creative/qianchuan
work.  After reviewing the diff, run with `--reclip` to enqueue only the
recording's current clip engine (set to `conservative` for the sample):

```bash
python scripts/retranscribe_recording.py --recording-id 9931 --reclip
```

Compare the generated clip with the preserved original audio at several
subtitle transitions, especially the first, middle, and final cue.  The old
SRT can be restored by copying the `.before-asr` sidecar back.  No database
schema change is required; the only persistent validation artifact is the
sidecar backup and regenerated clip files.

## Rollback

Set `ASR_MODEL`, `ASR_BEAM_SIZE`, and related ASR settings back to their prior
values on the GPU worker, restart that worker, restore the sidecar backup, and
use the existing reclip endpoint.  Keep ASR execution remote; do not enable
local heavy-media fallbacks or MPS.
