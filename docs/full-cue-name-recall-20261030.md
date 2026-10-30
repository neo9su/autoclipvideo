# Full-cue name recall integration

Production analysis previously ran name matching only on the bounded summary, excluding names elsewhere in the transcript. Added `wig_name_recall` to search every original cue against room-scoped title-derived names, including inactive products as historical naming references. Same-name product IDs are preserved. Up to three adjacent cues can form a name, with a maximum0.6s pause and12s source span. Generic title fragments are excluded; extracted titles and ASR remain fallible candidates.

Each report stores the subtitle hash, source timestamps, verbatim quote/context, catalogue IDs, and whether speech locally asserts the current item. `visual_verified`, `sku_verified` and automatic cart eligibility remain false. No SKU identity is inferred from a name mention alone. Evidence is saved under the application `identity_evidence/<recording-id>-names.json`, not on source media.

Analyzer receives a bounded candidate-evidence supplement after neutral transcription. Original sampled speech is retained separately for legacy keyword matching, preventing a name introduced by the supplement from being treated as observed speech. This does not yet replace legacy keyword-based grouping or add visual validation. Failed evidence collection is logged and existing analysis continues; such failures do not confer verification.

## Validation and deployment

19 targeted tests passed, covering room isolation, multiple links, split-name recovery, pause boundaries, future mentions, full-source retrieval and hint isolation. Production45497 was checked with the actual deployed helper:1,838 cues,20 candidate occurrences for ella/夺回&人生/琥珀精灵; these are not20 identities or a confirmed assignment. Evidence supplement length2,397 characters in this smoke check. No GPU inference or new video render was submitted.

Backup: `C:\Users\neo\douyin_backend\codex_rollbacks\name-recall-20261030-231823`.
Stage: `C:\Users\neo\douyin_backend\codex_operations\name-recall-20261030`.
Activated using the idle-guarded interactive backend maintenance helper. Existing production analyzer was narrowly patched; no unrelated files overwritten. The new helper was deployed dormant before activation. Rollback restores the previous analyzer and, after an idle restart, disconnects the helper while retaining diagnostic evidence.

Remaining work: full interval-level wearing/identity verification, safe grouping across recordings, explicit target intervals for variant selection, name-alias correction review, and actual rerender/playback validation. Existing generated media and historical group names were not rewritten. No retention or conversion improvement has been measured.
