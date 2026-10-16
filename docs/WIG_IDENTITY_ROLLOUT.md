# Single-wig metadata gate, version 1

## Scope

Generation must first establish one target wig style and color. Every transcribed
recording in the candidate pool must agree with that target and room. Multiple
product names or missing identity evidence require review. Explicit conflicts
cannot be overridden by a high semantic score, exact product ID, or threshold=0.

This first gate checks metadata, not pixels. `metadata_consistent` is not visual
approval, SKU confirmation, or permission to spend on ads. A recording containing
several wigs may still have one incorrect summary label. Shot-level boundaries,
rendered-frame checks, title/caption/cart validation and human approval remain
required follow-up work. Do not advertise this release as guaranteeing no mixing.

Learn hook/action/proof/CTA structure from viral samples only within the approved
same-product material pool. Do not borrow another wig to fill a shot or duration.

## Before production activation

1. Preserve exact production bytes in a local, access-controlled baseline. Never
   push environment files, cookies, database files, recordings or raw production
   snapshots to the public repository. Commit reviewed code and rollback tools.
2. Run `python scripts/audit_wig_identity.py --db ABSOLUTE_DB_PATH`. This opens the
   database read-only and does not enqueue jobs or probe media. Review affected
   groups, aliases and unknown metadata before enabling strict rejection.
3. Prepare against the ACTUAL live backend, not a repository copy:

   ```text
   python scripts/wig_identity_release.py prepare --backend BACKEND --release RELEASE --module backend/wig_identity.py
   ```

   RELEASE must be outside BACKEND. It contains exact original bytes, staged
   patched bytes, and a SHA-256 manifest. Existing releases are never overwritten.
4. Validate staged source, review the minimal diff, test both metadata checks and
   rollback on a disposable directory. Do not replace the live matcher wholesale:
   production may have fixes and thresholds absent from GitHub.
5. Establish a maintenance window with no active recording, generation or publish
   jobs affected by restart. The legacy API maps matcher rejection to -2; it does
   not yet have a dedicated persistent `review_required` state. Do not bulk-activate
   this gate until that operational consequence is accepted or addressed.
6. Apply with `python scripts/wig_identity_release.py apply --release RELEASE`,
   then restart through the site's approved launcher and verify runtime behavior.
   The script does NOT restart services. File replacement is not a transactional
   multi-file deploy; an interrupted apply needs recovery from `before/`.

## Rollback

Use `python scripts/wig_identity_release.py rollback --release RELEASE` in the
same maintenance window. It verifies deployed and backup hashes before any
mutation, restores the exact old matcher, and removes the newly introduced module.
If a subsequent edit is detected, it refuses to overwrite it; reconcile manually.
Restart the service and verify the restored runtime. A Git revert alone does not
undo a deployment to a different Windows source tree.

This release has no schema migration or automatic data writes. If the activated
legacy API has written rejection statuses, reverting code does NOT restore them.
Record affected task/group IDs during rollout; any data correction must be a
separately reviewed, bounded action. Never mass-reset historical failures.

## Validation

`python -m pytest tests/test_wig_identity.py tests/test_wig_identity_release.py -q`

Tests cover wrong style/color/room, ambiguous identity, multiple product names,
candidate rows beyond the latest five, legacy schemas, zero-threshold bypass,
read-only audits, CRLF/BOM preservation, source drift and exact-byte rollback.
