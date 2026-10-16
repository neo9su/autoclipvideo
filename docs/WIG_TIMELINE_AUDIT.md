# Timestamped wig evidence audit (shadow mode)

Whole-recording labels cannot establish that every shot shows one wig. This tool
reads complete SRT cues and writes review evidence with original in/out times,
recording ID, source/catalog hashes, and policy version. It never starts a render,
changes groups, writes the source database, or approves footage for delivery.

## Evidence rules

- Explicit unique product aliases are evidence only. Generic terms such as long
  curly hair, natural black, and no-cap are not product identities.
- Duplicate aliases across catalog rows remain ambiguous; no fuzzy SKU guessing.
- A cue mentioning several products or another target is marked for review.
- Possible current switches are separated from future sales discussion and
  common packaging/angle language. These are transcript candidates, not verified
  changes on screen. ASR errors and indirect references can still be missed.
- Spoken link/style/color numbers are retained separately. They are scoped to the
  recording; an "8号链接" is not a stable SKU across rooms, sessions or time.
  Changes between explicit link references create visual-review points only.
- Unknown cues do not inherit the previous product. No padding, gap fill or
  automatic merge bridges uncertain content.
- Overlapping/malformed times are reported. Raw transcript text is preserved;
  matching uses NFKC, case folding and a small documented business-character
  traditional/simplified map, not full Chinese normalization.
- Every segment has `eligible_for_render=false` and `approval=review_required`.
  A text-only single-product match never certifies the visible wig, color or SKU.

## Usage

```text
python scripts/audit_wig_timeline.py --db ABSOLUTE_DB_PATH --recording-id 123 --storage-root RECORDINGS_ROOT --output NEW_REPORT.json
```

Repeat `--recording-id` for at most 20 explicit recordings. Repeat `--storage-root`
for the actual storage and legacy roots. Both root-sidecar and room-subdirectory
SRT paths are checked. Unreadable, missing, over-10-MiB or non-UTF-8 inputs are
reported without triggering repairs. Output must be a new file; existing reports
are never overwritten. Optional `--target-key catalog:ID` requires that product to
exist in the room-scoped catalog used for that recording.

The current DB adapter uses catalog short names, which can be long marketing
names rather than what the host says. No alias hit means insufficient evidence,
not proof of one product. A separate reviewed mapping from spoken names/link
numbers to actual product and variant identities is needed before automatic use.

## Rollout and rollback

This is a standalone audit with no production imports, routes, worker changes or
schema migrations. Running it requires no service restart. Keep actual transcripts
and results outside the public Git repository. Version reviewed code, not media.

Rollback is a Git revert of the isolated audit commit, or removal of its standalone
staging directory; no source-data rollback is needed because the audit never writes
source data. Preserve exported reports as dated evidence rather than deleting or
silently replacing them. Do not activate the earlier runtime gate merely to use
this tool; production activation still requires the safe maintenance window.

## Validation

`python -m pytest tests/test_wig_timeline.py -q`

Tests cover product switches, unknown gaps, alias collisions, generic traits,
comparisons/negations, exact time ranges, malformed/overlapping cues, late-recording
changes, traditional ASR, reference-number scope, explicit bounded selection,
room filtering and byte-identical source database preservation.
