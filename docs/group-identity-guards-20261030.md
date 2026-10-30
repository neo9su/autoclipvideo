# Group reuse and fallback continuity guards

Verified live production behavior: `_get_or_create_group` reused a matching model/colour group and appended new product names, even when the old and new names conflicted. Its substring-based fallback did the same. `_select_realistic_window` enforced a six-second continuity threshold during scoring, but its no-score fallback selected the first scene candidates without this threshold.

Production-scoped changes:
- Both exact and fuzzy group reuse now require the same single non-generic product-name set. Unknown names, generic appearance labels, conflicting names and multi-name recordings do not authorize automatic reuse. This is a prerequisite only, not visual or SKU confirmation.
- The realistic/conservative fallback stops at a gap greater than six seconds, and stops adding subsequent segments when they would exceed the target maximum. Normal scoring is unchanged.

Existing groups, files and source recordings are not rewritten. The change can create more separate groups for uncertain recordings and can yield shorter fallback selections. It intentionally does not infer shared identity from appearance alone. An individual source recording can still show multiple products; interval verification and explicit target-window routing are still required.

Files changed in production: `backend/analyzer.py`, `backend/editor.py`, patched against live source rather than replacing them with the divergent local versions. Repository contains the scoped patch and staging scripts plus regression tests.

21 focused tests passed. Staged backup: `C:\Users\neo\douyin_backend\codex_rollbacks\group-identity-guards-20261030-232548`, including before/after hashes and rollback.py. Activation uses the existing idle-guarded interactive backend helper. No GPU work or media regeneration was submitted.
