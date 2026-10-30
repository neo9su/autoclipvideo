# CPU-only target-visibility risk hold

The previous 4B feature diagnostic treated hair on a tablet screen as the live
presenter, returning a stable-appearance candidate. Another intermediate
close-fitting head/net was labeled as visible loose hair. Feature consistency
cannot certify that the features belong to the intended person or a worn wig.

`scripts/audit_wig_visibility.py` reads the existing private sample manifest and
cached feature report, checks manifest/clip hashes, samples each clip at roughly
1 fps on one CPU thread, and writes a fresh report. No model is loaded, no GPU
or remote host is accessed and no original/report is overwritten.

A pair of large, tilted, approximately parallel borders straddling a fixed-camera
viewport anchor proposes a foreground-occlusion risk. This can catch partially
visible tablet edges where closed-contour rectangle detection fails. It is NOT
an object detector, a depth estimate or identity tracking. The viewport anchor
is a prior, not a verified face location. Axis-aligned devices, soft occlusions,
other angles and moving cameras can be missed; perspective background edges can
produce false holds. Do not tune the geometry to claim success on six examples.

Any proposed risk converts a cached stable/matching/conflict candidate to
`uncertain`, preserving the earlier candidate and evidence. A negative result
cannot certify visibility, absence of screens or a hair-net state. The guard
always leaves target/head/physical/SKU verification false, review required and
render eligibility false. A review-hold proposal does not need product identity
proof; approval would require independent target and head-state evidence which
this tool does not provide.

## Observed scope

The CPU pass inspected 318 timestamps in the six existing diagnostic clips.
Twelve frames in the tablet example triggered proposals; the other five clips
had none. The prior stable-appearance candidate was consequently held as
uncertain. These are selected debugging examples with assistant image-review
references, NOT a held-out human-labeled accuracy or recall measurement. No new
recordings or new VLM inference were used in this pass.

```text
python scripts/audit_wig_visibility.py --manifest PRIVATE_MANIFEST.json --feature-report CACHED_FEATURE_REPORT.json --output NEW_REPORT.json
```

## GPU resource boundary

New GPU-backed experiments must use the centralized AID scheduler and an actual
allow-listed profile. Do not execute historical direct model commands, private
worker ports or SSH workloads as a fallback. Read profiles/snapshot only after
`AID_GPU_MANAGER_URL` and a client key (or `AID_GPU_MANAGER_API_KEY_FILE`) are
configured. Keep credentials outside reports and chat. This CPU pass required
none of them and submitted no GPU job. A missing client configuration is not an
outage diagnosis or permission to install/administer the scheduler.

## Provenance and rollback

Earlier private diagnostic artifacts use legacy `human_review_note` and
`matches_human_label` names, but the labels were created by Codex image review.
They were not independent human annotations. Keep frozen artifacts to preserve
hashes, and attach a separate provenance correction. Future reports use
`matches_reference_label`. No operator has signed off the clips or SKU identity.

Revert the isolated CPU-guard/provenance commit to restore source. Generated
reports are outside runtime paths; preserve the dated evidence. No business DB,
service, source recording, dependency environment or task state changed. No
service restart, database restoration or media rollback is required. The next
required validation is independently annotated held-out footage and reliable
presenter/head-state tracking, through a configured scheduler if GPU-backed.
