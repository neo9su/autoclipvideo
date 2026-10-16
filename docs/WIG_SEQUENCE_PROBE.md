# Continuous wear/remove evaluation (shadow only)

The single-frame 500M probe missed visible features. This experiment uses
`mlx-community/Qwen3-VL-2B-Instruct-4bit`, fixed revision
`9c4f5209e57b31f4b9dfba735de3fb983739c9cc`, with `mlx-vlm==0.7.8` in a
separate local virtual environment. Source model and quantized model carry
Apache-2.0:
https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct
https://huggingface.co/mlx-community/Qwen3-VL-2B-Instruct-4bit

This is an Apple Metal test; unified-memory allocator peaks are NOT NVIDIA CUDA
VRAM measurements. Keep all original media, samples, human labels and reports
private. Only code, tests and methodology belong in the public repository.

## Inputs and isolation

`scripts/audit_wig_sequence.py` consumes 1–8 explicitly selected continuous clips,
each at most 150 seconds. A local manifest lists their SHA-256, recording ID,
source offset, duration and human appearance/action label. Source media is never
written. Exporting a sample must use a fresh output and preserve the full frame;
record resize, frame rate, re-encoding and audio omission. Do not concatenate
separate source moments to construct an allegedly continuous wear cycle.

The offline model snapshot is hash-checked by `verify_snapshot` shared with the
single-frame tool. The process uses a 6 GiB MLX allocator limit and 256 MiB cache
limit. It loads a native video processor (no silent still-image fallback), samples
at 1 or 2 fps with an explicit 32/64/128 frame cap, and logs actual sampled times.
The runtime's video pixel budget is for the ENTIRE clip, so it is explicitly set
to sampled-frame count times 256*256 pixels. Otherwise a long clip can be shrunk
to unhelpfully tiny per-frame views. This remains a bounded test configuration;
fast actions can occur between sampled frames.

```text
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 ISOLATED_PYTHON scripts/audit_wig_sequence.py --manifest PRIVATE_MANIFEST.json --model-dir VERIFIED_LOCAL_SNAPSHOT --output NEW_REPORT.json --fps 1 --max-frames 128
```

No API service, scheduler, database write, renderer, TTS or publication action is
created. No production dependency is installed, upgraded or uninstalled.

## Labels and uncertainty

The fixed prompt does not receive expected labels or human notes. The revised
protocol uses concise Chinese questions and the source model's recommended VL
sampling (temperature 0.7, top-p 0.8, top-k 20, presence penalty 1.5), with seed 0.
Greedy English-schema trial outputs are retained separately: repetition and
truncation are failures, not successful abstentions. A per-case `.progress.jsonl`
preserves observations if a later case fails. Prompt/code hashes, generation
settings and token counts are recorded. It asks for
before/after appearance, an event timeline and an explicit identity-gap flag.
Black close-fitting hair/net after removal is an unworn state, not a new black
product. Combing, tying and illumination are not alone proof of a product switch.

`visually_matching_rewear` means the visible style appears matching across a
remove/unworn/put-on cycle. It does NOT establish that the physical object or SKU
is the same. Preserve `identity_gap=true` when the wig leaves view. If appearance
or the target presenter cannot be compared, use `uncertain`. A different visible
style/color is also not a verified catalog identity.

Malformed/truncated JSON, invalid times and incomplete claimed rewear cycles
remain uncertain; never treat them as success. Every result is still
`review_required`, `eligible_for_render=false`, `sku_verified=false`. A handful
of selected examples cannot establish production accuracy. Record both raw and
validated model observations so a conservative parse does not hide model errors.

## Rollback

Stop only the explicit experiment process. Remove its isolated environment,
model cache and exported test copies when no longer needed, while retaining
reports and source provenance. Revert the experiment's isolated Git commits;
the shared snapshot-helper extraction is behavior-preserving and covered by the
existing visual-probe tests. No database restoration or production restart is
required. This code is not imported by workers.
