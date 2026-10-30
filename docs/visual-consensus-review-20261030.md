# Visual identity verification: unresolved model disagreement

The AID client profiles and snapshot were checked: qwen-vl-wig-203 remains enabled and203 was ONLINE with no scheduled running/queued jobs. Availability is not recognition accuracy. No GPU job was submitted in this review.

Reused actual independent jobs477,478,479 against the same source artifact for recording45409 instead of repeating the same failed prompt approach. Across45 unique sampled source timestamps, three have contradictory observations:

| Source second | Observed disagreement |
|---|---|
|458|Group inference says transition; single-image inference says stable wearing, with different colour/bangs descriptions. Prior frame review showed accessory removal, not proven wig removal.|
|550|One run says no wig; others say stable wearing with different length descriptions.|
|1423|One run says no wig; another says stable wearing. Prior human frame review identified the unworn/base-hair interval.|

1426 had different padding representations of unknown features; normalized this rather than reporting a false appearance conflict.

Added `backend/wig_visual_consensus.py` as an offline evidence-review helper. It requires the same source artifact and distinct job IDs, rejects invalid/duplicate timestamps, retains all original observations and flags disagreements. Neither high model confidence nor agreement grants visual verification, same-product merge permission or render eligibility. It is NOT installed as a production classifier.

11 targeted tests passed, covering conflicts, confidence handling, duplicate/source guards, unknown formatting and existing sequence analysis. Evidence report lives in the workspace at output/visual-identity-review/45409-consensus.json. No production backend restart, database mutation, media change, new model installation or222 upgrade occurred.

The existing CPU hair-region segmentation experiment is useful supporting evidence, but cannot prove whether hair is real or a wig. Its earlier24-frame evaluation is not enough for production accuracy. Next validation must use independent labelled continuous examples of genuine removal, accessory removal, base hair/hair nets, occlusion and actual change; no new threshold can be inferred from these few samples alone.

The product naming/full-cue improvements and group guards already deployed remain active. Automatic worn-product interval verification, target-specific variant selection, old-video regeneration and performance validation remain incomplete. This review must not be described as successful automated video identity recognition.
