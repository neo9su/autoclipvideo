# Group-targeted original-audio variant selection

Live realistic/conservative selection used `pick_best_window` to choose the longest/most complete introduction without receiving the group's target identity. Boundary prompts also explicitly treated generic appearance words as product names and did not request original speech evidence.

The scoped production patch passes group model, colour and product keywords into `edit_recording`. Targeted original-audio variants now select only a matching named boundary of at least45seconds, with matching colour when specified and a current-product quote corroborated against original cues inside that interval. Invalid timestamps, out-of-source limits, conflicting overlapping named windows, ambiguous target names/colours and unsupported quotes cause a review error rather than fallback to another product or the full recording. Unknown/generic target names are rejected before boundary model calls. A failed source can be skipped in favour of another source in the same group; the final failure retains the identity-review reason.

Boundary prompts now distinguish names from generic appearance and require current_evidence, rejecting future/comparison mentions as current confirmation. This is not visual verification: transcript-derived intervals can still be incorrect, and the existing name parser/alias coverage is deliberately limited. Name equality does not prove colour/version/SKU equality. No fuzzy spelling identity was added beyond the user-established 氧气粒子/氧气栗子 search alias; a raw quote still needs corroboration.

Production modified files: backend/editor.py, backend/transcribe.py, backend/wig_boundary.py; new backend/wig_target_window.py. Local divergent transcribe edits were not overwritten; production patches are carried by scripts/patch_target_window.py and scripts/stage_target_window.py. Unrelated production changes and the prior caption/selection guards are retained.

27 targeted tests passed, including selection of a shorter target over a longer other product; no fallback on colour/quote/length/overlap failures; generic/multiple targets; future-mention rejection; existing subtitle, name-recall and grouping regressions.

Backup: C:\Users\neo\douyin_backend\codex_rollbacks\target-window-20261030-234357. Before/after hashes and guarded rollback included. The module was staged dormant before activation. Rollback restores the three callers and disconnects the helper after an idle interactive backend restart. No GPU job, media regeneration, explicit database migration or222 upgrade was submitted.

Operational limit: more uncertain groups can now fail with a specific 目标款式待复核 reason instead of yielding an unrelated variant. The existing status schema records these as failures, not a dedicated review state. Historic failures/media were not bulk reset. Actual end-to-end render/playback and continuous visual identity validation remain incomplete.
