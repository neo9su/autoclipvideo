# Slash descriptions in wig window selection — 2026-10-25

Removed the unconditional slash/fullwidth-slash rejection from select_identity_windows. Descriptive parting alternatives expand with their shared suffix, e.g. 中分/侧分长款假发 matches 中分长款假发 and 侧分长款假发, without introducing a standalone 中分 alias that admits unrelated short wigs.

Slash-separated name/color alternatives require surviving boundaries to resolve to one name/color identity. Single observed alternatives may be selected. Confirmed different styles or different colors are never pooled into one output. Explicit & product aliases retain existing same-product behavior. Missing color evidence for a multi-color target remains unresolved; punctuation alone is not a mismatch.

Changed backend/wig_preprocess.py and targeted tests/test_wig_preprocess.py. Twelve tests passed, covering slash/fullwidth slash, parting alternatives, unrelated wig exclusion, same-wig rewear, distinct styles/colors and existing naming/spec policies.

Production patch replaced only the AST-delimited function after comparing the original function to the repository baseline; other production-only functions were preserved. CPU-only production import test selected both same-style parting windows, one identity, and excluded the unrelated wig. This is a policy test, not real-video recognition accuracy evidence. No manual GPU job submitted.

203 backup/audit/rollback: C:\Users\neo\douyin_backend\codex_rollbacks\slash-identity-20261025. rollback.py validates the current source hash before restoring the saved full source. Requires desktop-backend restart while publication is idle afterward.

Product scoring self-hits, inconsistent subtitle resolution and historical failed groups are outside this scoped change. Existing failures are not automatically reset. Full production generation remains unverified pending those repairs and an end-to-end AID execution test.
