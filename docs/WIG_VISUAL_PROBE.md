# Shadow visual probe

`scripts/audit_wig_visual.py` is an explicit-image experiment, outside all workers.
It uses SmolVLM-500M-Instruct pinned to
`a7da5b986cb59b408707209984f360a5f4ad7e47`, with remote code disabled.
No production DB, routes, task states, media files or configuration are changed.

## Model selection

- Jev is hosted; its image support is experimental:
  https://typesafe.ai/blog/jev-1-14
- Standard Laya checkpoints are text models:
  https://huggingface.co/convaiinnovations/laya
- Independent Laya Vision is 201M parameters but its weights carry
  CC-BY-NC-SA-4.0, unsuitable for direct adoption in this commercial pipeline:
  https://huggingface.co/thaitea/laya-vision
- SmolVLM-500M has Apache-2.0 weights and its card reports single-image inference
  at 1.23 GB GPU RAM. This is a vendor figure, not our measured deployment peak:
  https://huggingface.co/HuggingFaceTB/SmolVLM-500M-Instruct

## Experiment

Pass 1–12 explicit `--image` paths, a dedicated `--cache-dir`, a fresh `--output`,
and `--device cpu` (default). No installation or service endpoint is required if
PyTorch, Pillow and a compatible Transformers are already present. The model
weights download into the dedicated cache. Transformers 5 uses
`AutoModelForImageTextToText` rather than the removed `AutoModelForVision2Seq`.

The probe explicitly limits the longest edge to 512 pixels and disables image
splitting. It keeps the full frame rather than cropping a target person. This is
a measured configuration candidate, not the model default (2048px with splitting).

Questions separate people, hair appearance, evidence of wearing/removing a wig,
and occlusion. Responses are raw model observations, not trusted labels or
calibrated probabilities. Every result remains `review_required`,
`eligible_for_render=false`, `visual_verified=false`, `sku_verified=false`.

For restricted-network hosts, use `--model-dir` pointing to an offline snapshot.
Its `source_manifest.json` must match the pinned model/revision and all listed
file hashes are checked before inference; local-only loading prevents network
fallback. The weight file SHA-256 is
`d05b567eeaf534e83d375551f068ed57b5f52d37c657197f644af5ef9db091a2`.

CPU smoke tests must precede GPU measurements. Run CUDA only when it cannot
interrupt production work; record allocated and reserved peaks separately from
whole-device usage. Failures do not switch devices automatically. A failed run
may leave an incomplete reserved output: inspect its log and use a new filename.

Two still frames cannot validate a wear/remove cycle. Before connecting to
editing, label continuous clips covering wear, removal, rewear of the same wig,
actual product switches, black wigs, hair nets, multiple people, occlusion,
lighting changes and similar-color different styles. Unknown state and ambiguous
person identity must block automatic acceptance. Neither apparent black hair nor
model confidence proves natural hair or a SKU. Maintain per-person temporal
state; do not carry product identity across an unobserved interval as fact.

## Rollback

Stop only the explicit probe process if running. Remove the independent script
and dedicated model cache when no longer needed; preserve dated reports. Revert
the isolated Git commit to remove source. No service restart or DB restore is
needed. Never uninstall or upgrade production dependencies for this probe.
