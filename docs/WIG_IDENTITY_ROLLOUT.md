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
5. Stage the complete review workflow using the additional
   `--review-sources backend` argument. It patches the ACTUAL API and health
   implementation, including production-only v2 paths when present. Do not activate
   the matcher-only first release: legacy batch callers can ignore `match.ok`.
   The complete release adds persistent status -5 and returns before script/TTS
   execution in both pipeline and composition paths.
6. Stage the actual frontend with `prepare_wig_review_frontend.py`; build in an
   isolated directory, retain original dist and source, and check the deployed
   runtime UI after activation. The frontend in GitHub may lag production.
7. Establish a maintenance window with no recording/generation/publish job affected
   by restart. Do not interrupt a publishing browser to activate these changes.
8. Apply with `python scripts/wig_identity_release.py apply --release RELEASE`,
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

There is no schema migration. Once activated, a rejected generation request can
write -5 plus evidence and the original status/error/review snapshot. Code rollback
does NOT undo those rows. `rollback_wig_review_holds.py` requires explicit group IDs,
defaults to dry-run, and requires a new SQLite backup for `--apply`. It verifies
hold ownership and exact current evidence and never restores the entire live DB.
Interrupted running flags are restored as pending rather than phantom running jobs.
Keep later valid changes and unrelated historical failures untouched.

## Review behavior

- -5 means evidence review, not permanent failure; automatic retry allow-lists and
  startup claims exclude it. Health adds `qianchuan_review_required`.
- GET `/api/v2/qianchuan/group/{id}/identity-review` recomputes evidence read-only.
- POST `/api/v2/qianchuan/group/{id}/identity-recheck` recomputes evidence; it cannot
  override conflicts. Only repaired metadata releases a held row to pending (or
  preserves an artifact that was complete before the hold). It does not start TTS
  or certify visual identity. `version=qianchuan_v2` isolates v2 review fields.
- No historical groups are bulk-relabelled by deployment or the audit script.

## Validation

`python -m pytest tests/test_wig_identity.py tests/test_wig_identity_release.py tests/test_wig_identity_review.py tests/test_wig_review_data_rollback.py -q`

`node frontend/tests/qianchuan-review.test.mjs` and `npm --prefix frontend run build`

Tests cover wrong style/color/room, ambiguous identity, multiple product names,
candidate rows beyond the latest five, legacy schemas, zero-threshold bypass,
read-only audits, CRLF/BOM preservation, source drift and exact-byte rollback.
