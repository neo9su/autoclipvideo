## Runtime source of truth

Both GPU service distributions use the same profile: `large-v3`, explicit
Mandarin (`zh`), beam search, temperature fallback, VAD, word timestamps,
`condition_on_previous_text=False`, and the wig-commerce prompt. The checked-in
`gpu_service/asr_config.py` is used by the current FastAPI service; the
deployment source under `gpu_service_src/` imports its matching profile module
instead of maintaining a second set of decoding constants. This prevents a
source deployment from silently reverting to older settings.

The model and decoding values are deployment-local environment overrides. The
default remains accuracy-first for the RTX 4080 SUPER; changing them requires a
GPU service restart and should be followed by a single-recording SRT comparison.
