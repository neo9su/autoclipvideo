# Qianchuan generation failure diagnosis — 2026-10-25

Read-only inspection of production code/database and CPU-only replay; no LLM calls, GPU submissions, task resets or production matching changes. Evidence on 203: codex_rollbacks/qianchuan-diagnosis-20261025/report.json.

## Product matching

Production api_v2.py lines 613–621 explicitly call score_product_match with threshold=0.58. Production matcher default is 0.30; changing its default does not change this caller. Candidates are enabled products for the room (or no room), newest first, LIMIT 30. This can omit older true products; the specific true products for these samples have not been manually identified.

load_group_context reads subtitles only at legacy project recordings/<stem>.srt, up to 8000 characters per file and five recordings. It does not use the F-aware media resolver used by later preflight. CPU replay of groups 5407, 5371, 5406 and 5374 loaded zero subtitle characters. Stored preflight for 5406/5374 had readable F media and SRT. Path/evidence loading is inconsistent; do not assume footage lacks subtitles.

Historical group 5407 is named 网发 with no color; 5371 has only 焦色. These are material/color descriptors rather than verified product identities. Historical scores were 0.41 and 0.51 against 0.58.

The scoring numerator includes group label/model/color tokens, and the searched corpus itself includes those same group fields. Color/label bonuses can therefore be satisfied by the group rather than product evidence. Current-catalog replay (not a historical reconstruction; candidates changed) ranked product 72 假发女漫画刘海头顶补发片 for groups 5407/5371/5406 while its product-name token was missing. Group 5406 scored 0.847 with only group-name/color hits. Group 5374 ranked product 856 [黄脸干杯] with that product token missing. A high score is not evidence of the correct product. Simply lowering the threshold would compound this defect.

## Shot matching

api_v2.py lines 708–718 require at least max(3, number_of_script_segments - 1) matched scenes. Groups 5406 and 5374 have readable media/SRT in stored preflight, but matching=[], accepted_count=0 and no rejection reasons. The UI's generic error is not proof of a semantic script mismatch.

Before scene scoring, QianchuanMatcher._get_group_recordings filters all candidates through transcript identity windows, optional visual checks, then retains only complete subtitle cues inside the surviving windows. select_identity_windows rejects any target name containing slash/comma-like separators immediately.

5374 has target 中分/侧分长款假发; its slash deterministically causes zero approved windows regardless of the boundary result. Parting alternatives are not by themselves proof of different products. The current separator policy conflates such titles with multi-style identities. Its 深黑色/深棕色 color field also requires evidence-based disambiguation before editing.

5406 has no slash; its exact upstream exclusion remains unproven by stored review. Empty boundary output, name/color alias mismatch or visual rejection can all remove windows; current review does not preserve these layer-specific reasons. No model/service was invoked to manufacture missing evidence.

## Recommended repair order

1. Unify subtitle resolution with preflight and retain evidence-loading diagnostics.
2. Use catalog style aliases and genuine product evidence; do not count group self-hits as product confidence. Keep explicit product/style identity separate from color/features.
3. Resolve parting/format alternatives without treating every slash as a different wig; genuinely ambiguous multi-style footage still needs segmentation.
4. Preserve per-recording boundary/window/subtitle/visual rejection reasons and distinguish no source windows from low scene similarity.
5. Rebuild scripts from confirmed same-style source text before an independently authorized AID execution test.

These are recommendations, not deployed matching changes.
